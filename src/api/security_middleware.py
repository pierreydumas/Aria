# src/api/security_middleware.py
"""
🛡️ Security Middleware for Aria API

Provides FastAPI middleware for:
- Request validation and sanitization
- Rate limiting per IP/user
- Prompt injection detection in request bodies
- Security headers
- Audit logging

Usage:
    from security_middleware import SecurityMiddleware, add_security_headers
    
    app.add_middleware(SecurityMiddleware)
"""
import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("aria.security.middleware")


# =============================================================================
# Threat Detection Patterns
# =============================================================================

INJECTION_PATTERNS = [
    # Prompt injection attempts
    (re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s*instructions?", re.I), "prompt_injection"),
    (re.compile(r"forget\s+(everything|your)\s*instructions?", re.I), "prompt_injection"),
    (re.compile(r"you\s+are\s+now\s+a", re.I), "roleplay_override"),
    (re.compile(r"(DAN|jailbreak|bypass\s+safety)", re.I), "jailbreak"),
    (re.compile(r"system\s*prompt", re.I), "prompt_leak"),
    
    # SQL injection patterns
    (re.compile(r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION)\b.*\b(FROM|INTO|TABLE)\b)", re.I), "sql_injection"),
    (re.compile(r"(--|;|/\*|\*/|@@)", re.I), "sql_injection"),
    (re.compile(r"'\s*(OR|AND)\s*'?\d+'?\s*=\s*'?\d+", re.I), "sql_injection"),
    
    # XSS patterns
    (re.compile(r"<script[^>]*>", re.I), "xss"),
    (re.compile(r"javascript:", re.I), "xss"),
    (re.compile(r"on\w+\s*=", re.I), "xss"),
    
    # Path traversal
    (re.compile(r"\.\./|\.\.\\", re.I), "path_traversal"),
    
    # Command injection
    (re.compile(r"[;&|`$]\s*(cat|ls|rm|wget|curl|bash|sh|python)", re.I), "command_injection"),
]

# Endpoints that should be exempt from body scanning
EXEMPT_ENDPOINTS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
}

# Endpoint prefixes exempt from body scanning (internal management APIs
# that legitimately use cron expressions like */30, SQL-like payload text, etc.)
EXEMPT_PREFIXES = (
    "/engine/cron",
    "/engine/chat",
    "/engine/sessions",
    "/graphql",
)

# Endpoints that serve interactive docs and need frontend assets/scripts
DOCS_ENDPOINTS = {
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}

# Sensitive field names that should be redacted in logs
SENSITIVE_FIELDS = {"password", "api_key", "token", "secret", "authorization", "credentials"}


# =============================================================================
# Rate Limiting
# =============================================================================

class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 500,
        burst_limit: int = 10,
    ):
        self.rpm = requests_per_minute
        self.rph = requests_per_hour
        self.burst = burst_limit
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._blocked: dict[str, float] = {}
    
    def is_allowed(self, identifier: str) -> tuple[bool, str | None]:
        """Check if request is allowed."""
        now = time.time()
        
        # Check if blocked
        if identifier in self._blocked:
            if now < self._blocked[identifier]:
                return False, "rate_limited"
            del self._blocked[identifier]
        
        # Clean old entries
        cutoff_hour = now - 3600
        self._requests[identifier] = [
            ts for ts in self._requests[identifier] if ts > cutoff_hour
        ]
        
        requests = self._requests[identifier]
        
        # Check burst (5 seconds)
        burst_count = sum(1 for ts in requests if ts > now - 5)
        if burst_count >= self.burst:
            self._blocked[identifier] = now + 15  # Short block for bursts
            return False, "burst_exceeded"
        
        # Check per-minute
        minute_count = sum(1 for ts in requests if ts > now - 60)
        if minute_count >= self.rpm:
            self._blocked[identifier] = now + 30
            return False, "rpm_exceeded"
        
        # Check per-hour
        if len(requests) >= self.rph:
            self._blocked[identifier] = now + 300
            return False, "rph_exceeded"
        
        # Record request
        requests.append(now)
        return True, None


# =============================================================================
# Security Middleware
# =============================================================================

class SecurityMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for security checks.
    
    Checks:
    - Rate limiting by IP
    - Request body scanning for injection
    - Request size limits
    - Security headers on response
    """
    
    def __init__(
        self,
        app: ASGIApp,
        rate_limiter: RateLimiter | None = None,
        max_body_size: int = 1_000_000,  # 1MB default
        scan_body: bool = True,
        blocked_ips: set[str] | None = None,
    ):
        super().__init__(app)
        self.rate_limiter = rate_limiter or RateLimiter()
        self.max_body_size = max_body_size
        self.scan_body = scan_body
        self.blocked_ips = blocked_ips or set()
        self._threat_counts: dict[str, int] = defaultdict(int)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through security checks."""
        start_time = time.time()
        client_ip = self._get_client_ip(request)
        
        # Check blocked IPs
        if client_ip in self.blocked_ips:
            logger.warning(f"Blocked IP attempted access: {client_ip}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied"},
            )
        
        # Skip security for exempt endpoints
        if request.url.path in EXEMPT_ENDPOINTS:
            response = await call_next(request)
            return self._add_security_headers(response, request.url.path)
        
        # Skip body scanning for exempt prefix paths (internal APIs)
        path = request.url.path.rstrip("/")
        # Strip /api prefix if present
        scan_path = path[4:] if path.startswith("/api") else path
        skip_body_scan = any(scan_path.startswith(p) for p in EXEMPT_PREFIXES)
        
        # Skip rate limiting for safe read methods (GET/HEAD/OPTIONS)
        # Dashboard pages fire many concurrent GET requests for charts/stats
        if request.method in ("GET", "HEAD", "OPTIONS"):
            response = await call_next(request)
            return self._add_security_headers(response, request.url.path)
        
        # Rate limiting (POST/PUT/PATCH/DELETE only)
        allowed, reason = self.rate_limiter.is_allowed(client_ip)
        if not allowed:
            logger.warning(f"Rate limit exceeded for {client_ip}: {reason}")
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded: {reason}"},
                headers={"Retry-After": "60"},
            )
        
        # Check content length
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_body_size:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
        
        # Scan request body for threats (skip exempt paths)
        if self.scan_body and not skip_body_scan and request.method in ("POST", "PUT", "PATCH"):
            body_scan_result = await self._scan_body(request)
            if body_scan_result:
                threat_type, pattern = body_scan_result
                self._threat_counts[threat_type] += 1
                logger.warning(
                    f"Security threat detected: {threat_type} from {client_ip} "
                    f"on {request.url.path}"
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": "Request blocked for security reasons",
                        "threat_type": threat_type,
                    },
                )
        
        # Process request
        response = await call_next(request)
        
        # Add security headers
        response = self._add_security_headers(response, request.url.path)
        
        # Log request
        duration = time.time() - start_time
        logger.debug(
            f"{request.method} {request.url.path} - {response.status_code} "
            f"({duration:.3f}s) from {client_ip}"
        )
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request."""
        # Check X-Forwarded-For header (for reverse proxy)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        # Check X-Real-IP header
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fallback to direct client
        if request.client:
            return request.client.host
        
        return "unknown"
    
    async def _scan_body(self, request: Request) -> tuple[str, str] | None:
        """Scan request body for security threats."""
        try:
            # Read body (need to cache it for the actual handler)
            body = await request.body()
            
            if not body:
                return None
            
            # Try to decode as text
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                return None  # Binary content, skip scanning
            
            # Check for injection patterns
            for pattern, threat_type in INJECTION_PATTERNS:
                if pattern.search(text):
                    return (threat_type, pattern.pattern)
            
            # Try to parse as JSON and check nested values
            try:
                data = json.loads(text)
                threat = self._scan_dict(data)
                if threat:
                    return threat
            except json.JSONDecodeError:
                pass
            
            return None
            
        except Exception as e:
            logger.error(f"Body scan error: {e}")
            return None
    
    def _scan_dict(self, data: Any, depth: int = 0) -> tuple[str, str] | None:
        """Recursively scan dict/list for threats."""
        if depth > 10:  # Prevent deep recursion
            return None
        
        if isinstance(data, dict):
            for key, value in data.items():
                # Check key itself
                if isinstance(key, str):
                    for pattern, threat_type in INJECTION_PATTERNS:
                        if pattern.search(key):
                            return (threat_type, pattern.pattern)
                
                # Recurse into value
                threat = self._scan_dict(value, depth + 1)
                if threat:
                    return threat
                    
        elif isinstance(data, list):
            for item in data:
                threat = self._scan_dict(item, depth + 1)
                if threat:
                    return threat
                    
        elif isinstance(data, str):
            for pattern, threat_type in INJECTION_PATTERNS:
                if pattern.search(data):
                    return (threat_type, pattern.pattern)
        
        return None
    
    def _add_security_headers(self, response: Response, request_path: str = "") -> Response:
        """Add security headers to response."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"

        path = request_path.rstrip("/") or "/"
        if path.startswith("/api"):
            path = path[4:] or "/"

        # Docs UI requires JS/CSS/image assets and inline bootstrap script.
        # Keep strict CSP everywhere else.
        if path in DOCS_ENDPOINTS:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "font-src 'self' data: https://cdn.jsdelivr.net; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "frame-ancestors 'none'"
            )
        
        return response
    
    def get_threat_stats(self) -> dict[str, int]:
        """Get threat detection statistics."""
        return dict(self._threat_counts)


# =============================================================================
# Helper Functions
# =============================================================================

def add_security_middleware(
    app: FastAPI,
    rate_limit_rpm: int = 60,
    rate_limit_rph: int = 500,
    max_body_size: int = 1_000_000,
    blocked_ips: set[str] | None = None,
) -> SecurityMiddleware:
    """
    Add security middleware to FastAPI app.
    
    Args:
        app: FastAPI application
        rate_limit_rpm: Requests per minute per IP
        rate_limit_rph: Requests per hour per IP
        max_body_size: Maximum request body size in bytes
        blocked_ips: Set of blocked IP addresses
        
    Returns:
        SecurityMiddleware instance
    """
    rate_limiter = RateLimiter(
        requests_per_minute=rate_limit_rpm,
        requests_per_hour=rate_limit_rph,
    )
    
    middleware = SecurityMiddleware(
        app=app,
        rate_limiter=rate_limiter,
        max_body_size=max_body_size,
        blocked_ips=blocked_ips or set(),
    )
    
    app.add_middleware(
        SecurityMiddleware,
        rate_limiter=rate_limiter,
        max_body_size=max_body_size,
        blocked_ips=blocked_ips or set(),
    )
    
    logger.info(f"🛡️ Security middleware added (RPM: {rate_limit_rpm}, body limit: {max_body_size})")
    
    return middleware


def sanitize_log_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize data for safe logging.
    
    Redacts sensitive fields.
    """
    result = {}
    
    for key, value in data.items():
        key_lower = key.lower()
        
        if any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS):
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = sanitize_log_data(value)
        elif isinstance(value, str) and len(value) > 200:
            result[key] = value[:200] + "...[truncated]"
        else:
            result[key] = value
    
    return result


def validate_content_type(request: Request, allowed: list[str]) -> bool:
    """
    Validate request content type.
    
    Args:
        request: FastAPI request
        allowed: List of allowed content types
        
    Returns:
        True if content type is allowed
    """
    content_type = request.headers.get("content-type", "")
    return any(ct in content_type for ct in allowed)
