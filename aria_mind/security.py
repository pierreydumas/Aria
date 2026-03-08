# aria_mind/security.py
"""
🛡️ Aria Security Module - Defense against prompt injection and malicious inputs.

This module provides comprehensive protection for Aria against:
- Prompt injection attacks (jailbreaking, instruction override)
- Malicious API inputs (XSS, SQL injection patterns)
- Data exfiltration attempts
- Rate limiting abuse
- Privilege escalation

Security Layers:
1. Input Sanitization - Clean and validate all inputs
2. Prompt Analysis - Detect injection patterns
3. Output Filtering - Prevent data leakage
4. Rate Limiting - Prevent abuse
5. Audit Logging - Track security events
"""
import hashlib
import html
import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from typing import Any, Callable, TypeVar
from collections import defaultdict

logger = logging.getLogger("aria.security")


# =============================================================================
# Severity Levels
# =============================================================================

class ThreatLevel(Enum):
    """Threat severity classification."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# =============================================================================
# Prompt Injection Detection
# =============================================================================

@dataclass
class InjectionPattern:
    """A pattern used to detect prompt injection attempts."""
    name: str
    pattern: re.Pattern
    severity: ThreatLevel
    description: str


# Pre-compiled patterns for performance
INJECTION_PATTERNS: list[InjectionPattern] = [
    # Direct instruction override attempts
    InjectionPattern(
        name="ignore_previous",
        pattern=re.compile(
            r"ignore\s+(all\s+)?(previous|above|prior|earlier|your|these)\s*(instructions?|rules?|prompts?|context)?",
            re.IGNORECASE
        ),
        severity=ThreatLevel.CRITICAL,
        description="Attempt to override system instructions"
    ),
    InjectionPattern(
        name="forget_instructions",
        pattern=re.compile(
            r"forget\s+(everything|all|your)\s*(instructions?|training|rules?|prompts?)?",
            re.IGNORECASE
        ),
        severity=ThreatLevel.CRITICAL,
        description="Attempt to reset AI instructions"
    ),
    InjectionPattern(
        name="new_instructions",
        pattern=re.compile(
            r"(new|updated?|different|override|replacement?)\s*(instructions?|rules?|persona|system\s*prompt)",
            re.IGNORECASE
        ),
        severity=ThreatLevel.HIGH,
        description="Attempt to inject new instructions"
    ),
    InjectionPattern(
        name="roleplay_override",
        pattern=re.compile(
            r"(you\s+are\s+now|from\s+now\s+on\s+you\s+are|pretend\s+to\s+be|act\s+as\s+if\s+you\s+are|roleplay\s+as)",
            re.IGNORECASE
        ),
        severity=ThreatLevel.HIGH,
        description="Attempt to change AI persona"
    ),
    InjectionPattern(
        name="system_prompt_leak",
        pattern=re.compile(
            r"(show|reveal|display|print|output|tell\s+me|what\s+is|what\s+are)\s*(me\s+)?(your\s+)?(system\s*prompt|instructions?|initial\s*prompt|hidden\s*prompt|rules)",
            re.IGNORECASE
        ),
        severity=ThreatLevel.HIGH,
        description="Attempt to extract system prompt"
    ),
    InjectionPattern(
        name="developer_mode",
        pattern=re.compile(
            r"(developer|debug|admin|sudo|root|maintenance)\s*(mode|access|override)",
            re.IGNORECASE
        ),
        severity=ThreatLevel.CRITICAL,
        description="Attempt to enable privileged mode"
    ),
    InjectionPattern(
        name="dan_jailbreak",
        pattern=re.compile(
            r"(DAN|do\s+anything\s+now|jailbreak|bypass\s+(safety|restrictions?|filters?))",
            re.IGNORECASE
        ),
        severity=ThreatLevel.CRITICAL,
        description="Known jailbreak technique"
    ),
    InjectionPattern(
        name="hypothetical_bypass",
        pattern=re.compile(
            r"(hypothetically|theoretically|in\s+a\s+story|fictional)\s*.{0,30}(how\s+would|how\s+to|explain)",
            re.IGNORECASE
        ),
        severity=ThreatLevel.MEDIUM,
        description="Hypothetical scenario bypass attempt"
    ),
    InjectionPattern(
        name="base64_injection",
        pattern=re.compile(
            r"(decode|execute|run|eval)\s*(this\s+)?base64|[A-Za-z0-9+/]{50,}={0,2}",
            re.IGNORECASE
        ),
        severity=ThreatLevel.HIGH,
        description="Base64 encoded payload injection"
    ),
    InjectionPattern(
        name="delimiter_injection",
        pattern=re.compile(
            r"(```|\[\[|\{\{|<\|).*?(system|assistant|user|prompt).*?(```|\]\]|\}\}|\|>)",
            re.IGNORECASE | re.DOTALL
        ),
        severity=ThreatLevel.HIGH,
        description="Delimiter-based injection attempt"
    ),
    InjectionPattern(
        name="prompt_leaking",
        pattern=re.compile(
            r"(repeat|echo|print)\s*(back\s+)?(everything|all|the\s+text)\s*(above|before|from\s+start)",
            re.IGNORECASE
        ),
        severity=ThreatLevel.MEDIUM,
        description="Attempt to leak context/prompt"
    ),
    InjectionPattern(
        name="api_key_request",
        pattern=re.compile(
            r"(show|reveal|give|tell|what\s+is)\s*(me\s+)?(your\s+)?(api\s*key|secret|password|token|credentials?)",
            re.IGNORECASE
        ),
        severity=ThreatLevel.CRITICAL,
        description="Attempt to extract credentials"
    ),
    InjectionPattern(
        name="code_execution",
        pattern=re.compile(
            r"(execute|run|eval)\s*(this\s+)?(code|script|command|shell)",
            re.IGNORECASE
        ),
        severity=ThreatLevel.HIGH,
        description="Code execution request"
    ),
    InjectionPattern(
        name="unicode_bypass",
        pattern=re.compile(
            r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]",  # Zero-width and directional chars
            re.UNICODE
        ),
        severity=ThreatLevel.MEDIUM,
        description="Unicode obfuscation detected"
    ),
]


@dataclass
class InjectionResult:
    """Result of injection analysis."""
    is_safe: bool
    threat_level: ThreatLevel
    detections: list[dict[str, Any]] = field(default_factory=list)
    sanitized_input: str | None = None
    
    @property
    def blocked(self) -> bool:
        return self.threat_level in (ThreatLevel.MEDIUM, ThreatLevel.HIGH, ThreatLevel.CRITICAL)


class PromptGuard:
    """
    Protects against prompt injection attacks.
    
    Usage:
        guard = PromptGuard()
        result = guard.analyze("user input here")
        if result.blocked:
            return "Request blocked for security reasons"
    """
    
    def __init__(
        self,
        custom_patterns: list[InjectionPattern] | None = None,
        block_threshold: ThreatLevel = ThreatLevel.HIGH,
    ):
        self.patterns = INJECTION_PATTERNS + (custom_patterns or [])
        self.block_threshold = ThreatLevel.MEDIUM  # ARIA-REV-102: block MEDIUM+ threats
        self._severity_order = [
            ThreatLevel.NONE,
            ThreatLevel.LOW,
            ThreatLevel.MEDIUM,
            ThreatLevel.HIGH,
            ThreatLevel.CRITICAL,
        ]
    
    def analyze(self, text: str) -> InjectionResult:
        """
        Analyze text for injection attempts.
        
        Args:
            text: Input text to analyze
            
        Returns:
            InjectionResult with analysis details
        """
        if not text:
            return InjectionResult(is_safe=True, threat_level=ThreatLevel.NONE)
        
        detections = []
        max_severity = ThreatLevel.NONE
        
        for pattern in self.patterns:
            matches = pattern.pattern.findall(text)
            if matches:
                detections.append({
                    "pattern": pattern.name,
                    "severity": pattern.severity.value,
                    "description": pattern.description,
                    "matches": len(matches) if isinstance(matches, list) else 1,
                })
                
                if self._severity_order.index(pattern.severity) > self._severity_order.index(max_severity):
                    max_severity = pattern.severity
        
        # Additional heuristics
        heuristic_detections = self._heuristic_analysis(text)
        detections.extend(heuristic_detections)
        
        for det in heuristic_detections:
            sev = ThreatLevel(det["severity"])
            if self._severity_order.index(sev) > self._severity_order.index(max_severity):
                max_severity = sev
        
        is_blocked = self._severity_order.index(max_severity) >= self._severity_order.index(self.block_threshold)
        
        return InjectionResult(
            is_safe=not is_blocked,
            threat_level=max_severity,
            detections=detections,
            sanitized_input=self._sanitize(text) if not is_blocked else None,
        )
    
    def _heuristic_analysis(self, text: str) -> list[dict[str, Any]]:
        """Additional heuristic checks."""
        detections = []
        
        # Check for unusual character density
        special_char_ratio = len(re.findall(r'[^\w\s]', text)) / max(len(text), 1)
        if special_char_ratio > 0.3:
            detections.append({
                "pattern": "high_special_char_density",
                "severity": ThreatLevel.LOW.value,
                "description": f"Unusual special character density: {special_char_ratio:.2%}",
                "matches": 1,
            })
        
        # Check for repeated suspicious keywords
        suspicious_words = ['ignore', 'forget', 'override', 'bypass', 'admin', 'sudo', 'system']
        word_lower = text.lower()
        suspicious_count = sum(1 for word in suspicious_words if word in word_lower)
        if suspicious_count >= 3:
            detections.append({
                "pattern": "suspicious_keyword_cluster",
                "severity": ThreatLevel.MEDIUM.value,
                "description": f"Multiple suspicious keywords detected: {suspicious_count}",
                "matches": suspicious_count,
            })
        
        # Check for extremely long input (potential context exhaustion)
        if len(text) > 10000:
            detections.append({
                "pattern": "context_exhaustion",
                "severity": ThreatLevel.MEDIUM.value,
                "description": f"Unusually long input: {len(text)} characters",
                "matches": 1,
            })
        
        return detections
    
    def _sanitize(self, text: str) -> str:
        """Basic sanitization of text."""
        # Remove zero-width characters
        text = re.sub(r'[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]', '', text)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text


# =============================================================================
# Input Sanitization
# =============================================================================

class InputSanitizer:
    """
    Sanitizes and validates various input types.
    
    Provides protection against:
    - XSS (Cross-Site Scripting)
    - SQL Injection patterns
    - Path traversal
    - Command injection
    """
    
    # Dangerous SQL patterns
    SQL_PATTERNS = [
        re.compile(r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE|TRUNCATE)\b.*\b(FROM|INTO|TABLE|DATABASE)\b)", re.IGNORECASE),
        re.compile(r"(--|;|/\*|\*/|@@|@|\bchar\b|\bnchar\b|\bvarchar\b|\bnvarchar\b)", re.IGNORECASE),
        re.compile(r"(\bOR\b|\bAND\b)\s*[\d\w'\"]+\s*=\s*[\d\w'\"]+", re.IGNORECASE),
        re.compile(r"'\s*(OR|AND)\s*'?\d+'?\s*=\s*'?\d+", re.IGNORECASE),
    ]
    
    # Path traversal patterns
    PATH_PATTERNS = [
        re.compile(r"\.\./|\.\.\\"),
        re.compile(r"(^|/)\.\.(/|$)"),
        re.compile(r"%2e%2e[%/]", re.IGNORECASE),
    ]
    
    # Command injection patterns
    COMMAND_PATTERNS = [
        re.compile(r"[;&|`$]"),
        re.compile(r"\$\(|\$\{"),
        re.compile(r"\b(cat|ls|rm|mv|cp|wget|curl|bash|sh|python|perl|ruby|nc|netcat)\b", re.IGNORECASE),
    ]
    
    @classmethod
    def sanitize_html(cls, text: str) -> str:
        """Escape HTML entities to prevent XSS."""
        return html.escape(text, quote=True)
    
    @classmethod
    def sanitize_for_logging(cls, text: str, max_length: int = 1000) -> str:
        """Sanitize text for safe logging."""
        # Remove control characters
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length] + "...[truncated]"
        return text
    
    @classmethod
    def check_sql_injection(cls, text: str) -> tuple[bool, str | None]:
        """
        Check for SQL injection patterns.
        
        Returns:
            (is_safe, reason)
        """
        for pattern in cls.SQL_PATTERNS:
            if pattern.search(text):
                return False, f"SQL injection pattern detected"
        return True, None
    
    @classmethod
    def check_path_traversal(cls, path: str) -> tuple[bool, str | None]:
        """
        Check for path traversal attempts.
        
        Returns:
            (is_safe, reason)
        """
        for pattern in cls.PATH_PATTERNS:
            if pattern.search(path):
                return False, "Path traversal attempt detected"
        return True, None
    
    @classmethod
    def check_command_injection(cls, text: str) -> tuple[bool, str | None]:
        """
        Check for command injection patterns.
        
        Returns:
            (is_safe, reason)
        """
        for pattern in cls.COMMAND_PATTERNS:
            if pattern.search(text):
                return False, "Command injection pattern detected"
        return True, None
    
    @classmethod
    def sanitize_identifier(cls, name: str, allow_dots: bool = False) -> str:
        """
        Sanitize a database/variable identifier.
        Only allows alphanumeric and underscore.
        """
        pattern = r'[^a-zA-Z0-9_.]' if allow_dots else r'[^a-zA-Z0-9_]'
        return re.sub(pattern, '', name)
    
    @classmethod
    def validate_json_key(cls, key: str) -> bool:
        """Validate a JSON key is safe."""
        return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', key))


# =============================================================================
# Rate Limiting
# =============================================================================

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 60
    requests_per_hour: int = 500
    burst_limit: int = 10  # Max requests in 5 seconds
    cooldown_seconds: int = 60  # Cooldown after limit hit


class RateLimiter:
    """
    Token bucket rate limiter with multiple time windows.
    
    Usage:
        limiter = RateLimiter()
        if limiter.is_allowed("user_123"):
            # Process request
        else:
            # Rate limited
    """
    
    def __init__(self, config: RateLimitConfig | None = None):
        self.config = config or RateLimitConfig()
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._cooldowns: dict[str, float] = {}
    
    def is_allowed(self, identifier: str) -> bool:
        """Check if request is allowed for identifier."""
        now = time.time()
        
        # Check cooldown
        if identifier in self._cooldowns:
            if now < self._cooldowns[identifier]:
                return False
            del self._cooldowns[identifier]
        
        # Clean old entries
        self._cleanup(identifier, now)
        
        requests = self._requests[identifier]
        
        # Check burst limit (last 5 seconds)
        burst_cutoff = now - 5
        burst_count = sum(1 for ts in requests if ts > burst_cutoff)
        if burst_count >= self.config.burst_limit:
            self._cooldowns[identifier] = now + self.config.cooldown_seconds
            logger.warning(f"Rate limit: burst exceeded for {identifier}")
            return False
        
        # Check per-minute limit
        minute_cutoff = now - 60
        minute_count = sum(1 for ts in requests if ts > minute_cutoff)
        if minute_count >= self.config.requests_per_minute:
            self._cooldowns[identifier] = now + self.config.cooldown_seconds
            logger.warning(f"Rate limit: per-minute exceeded for {identifier}")
            return False
        
        # Check per-hour limit
        hour_cutoff = now - 3600
        hour_count = sum(1 for ts in requests if ts > hour_cutoff)
        if hour_count >= self.config.requests_per_hour:
            self._cooldowns[identifier] = now + self.config.cooldown_seconds * 5
            logger.warning(f"Rate limit: per-hour exceeded for {identifier}")
            return False
        
        # Record this request
        requests.append(now)
        return True
    
    def _cleanup(self, identifier: str, now: float):
        """Remove entries older than 1 hour."""
        cutoff = now - 3600
        self._requests[identifier] = [
            ts for ts in self._requests[identifier] if ts > cutoff
        ]
    
    def get_status(self, identifier: str) -> dict[str, Any]:
        """Get rate limit status for identifier."""
        now = time.time()
        self._cleanup(identifier, now)
        requests = self._requests[identifier]
        
        return {
            "requests_last_minute": sum(1 for ts in requests if ts > now - 60),
            "requests_last_hour": len(requests),
            "in_cooldown": identifier in self._cooldowns,
            "cooldown_remaining": max(0, self._cooldowns.get(identifier, 0) - now),
        }


# =============================================================================
# Output Filtering
# =============================================================================

class OutputFilter:
    """
    Filters sensitive data from outputs.
    
    Prevents accidental leakage of:
    - API keys
    - Passwords
    - Internal paths
    - System information
    """
    
    SENSITIVE_PATTERNS = [
        (re.compile(r'\b[A-Za-z0-9]{32,}\b'), '[REDACTED_KEY]'),  # Long alphanumeric strings
        (re.compile(r'(api[_-]?key|apikey)\s*[=:]\s*[^\s,}]+', re.IGNORECASE), 'api_key=[REDACTED]'),
        # Password pattern: matches "password": "value" or password=value or password: value
        (re.compile(r'"?(password|passwd|pwd)"?\s*[=:]\s*"?[^",}\s]+', re.IGNORECASE), '"password": "[REDACTED]"'),
        (re.compile(r'(secret|token)\s*[=:]\s*[^\s,}]+', re.IGNORECASE), 'secret=[REDACTED]'),
        (re.compile(r'Bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+', re.IGNORECASE), 'Bearer [REDACTED_JWT]'),
        (re.compile(r'(sk-|pk_live_|pk_test_)[A-Za-z0-9]+'), '[REDACTED_API_KEY]'),
        (re.compile(r'postgres://[^\s]+'), 'postgres://[REDACTED]'),
        (re.compile(r'mongodb://[^\s]+'), 'mongodb://[REDACTED]'),
        (re.compile(r'redis://[^\s]+'), 'redis://[REDACTED]'),
    ]
    
    # Paths that should not be revealed
    SENSITIVE_PATHS = [
        '/root/',
        '/etc/passwd',
        '/etc/shadow',
        '.env',
        'credentials',
        'secrets',
    ]
    
    @classmethod
    def filter_output(cls, text: str, strict: bool = False) -> str:
        """
        Filter sensitive data from output.
        
        Args:
            text: Text to filter
            strict: If True, be more aggressive with filtering
            
        Returns:
            Filtered text
        """
        result = text
        
        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            result = pattern.sub(replacement, result)
        
        # Filter sensitive paths
        for path in cls.SENSITIVE_PATHS:
            if path in result.lower():
                result = re.sub(
                    re.escape(path),
                    '[REDACTED_PATH]',
                    result,
                    flags=re.IGNORECASE
                )
        
        if strict:
            # In strict mode, also filter anything that looks like a file path
            result = re.sub(
                r'(/[\w\-./]+){3,}',
                '[REDACTED_PATH]',
                result
            )
        
        return result
    
    @classmethod
    def contains_sensitive(cls, text: str) -> bool:
        """Check if text contains sensitive data."""
        for pattern, _ in cls.SENSITIVE_PATTERNS:
            if pattern.search(text):
                return True
        return False


# =============================================================================
# Security Audit Logger
# =============================================================================

@dataclass
class SecurityEvent:
    """A security-related event."""
    timestamp: datetime
    event_type: str
    severity: ThreatLevel
    source: str
    details: dict[str, Any]
    blocked: bool = False


class SecurityAuditLog:
    """
    Maintains an audit log of security events.
    
    Events are stored in memory with optional persistence callback.
    """
    
    def __init__(
        self,
        max_events: int = 1000,
        persist_callback: Callable[[SecurityEvent], None] | None = None,
    ):
        self._events: list[SecurityEvent] = []
        self._max_events = max_events
        self._persist = persist_callback
    
    def log(
        self,
        event_type: str,
        severity: ThreatLevel,
        source: str,
        details: dict[str, Any],
        blocked: bool = False,
    ):
        """Log a security event."""
        event = SecurityEvent(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            severity=severity,
            source=source,
            details=details,
            blocked=blocked,
        )
        
        self._events.append(event)
        
        # Trim if over max
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        
        # Persist if callback provided
        if self._persist:
            try:
                self._persist(event)
            except Exception as e:
                logger.error(f"Failed to persist security event: {e}")
        
        # Log to standard logger based on severity
        log_msg = f"[{event_type}] {source}: {details}"
        if severity == ThreatLevel.CRITICAL:
            logger.critical(log_msg)
        elif severity == ThreatLevel.HIGH:
            logger.error(log_msg)
        elif severity == ThreatLevel.MEDIUM:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)
    
    def get_events(
        self,
        since: datetime | None = None,
        severity: ThreatLevel | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[SecurityEvent]:
        """Query security events."""
        events = self._events
        
        if since:
            events = [e for e in events if e.timestamp >= since]
        
        if severity:
            events = [e for e in events if e.severity == severity]
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        return events[-limit:]
    
    def get_summary(self, hours: int = 24) -> dict[str, Any]:
        """Get summary of recent security events."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = [e for e in self._events if e.timestamp >= cutoff]
        
        by_severity = defaultdict(int)
        by_type = defaultdict(int)
        blocked_count = 0
        
        for event in recent:
            by_severity[event.severity.value] += 1
            by_type[event.event_type] += 1
            if event.blocked:
                blocked_count += 1
        
        return {
            "period_hours": hours,
            "total_events": len(recent),
            "blocked_count": blocked_count,
            "by_severity": dict(by_severity),
            "by_type": dict(by_type),
        }


# =============================================================================
# Unified Security Gateway
# =============================================================================

class AriaSecurityGateway:
    """
    Unified security gateway for Aria.
    
    Combines all security measures into a single interface.
    
    Usage:
        security = AriaSecurityGateway()
        
        # Check user input
        result = security.check_input(user_message, source="chat")
        if not result.allowed:
            return result.rejection_message
        
        # Process with sanitized input
        response = process(result.sanitized_input)
        
        # Filter output
        safe_response = security.filter_output(response)
    """
    
    def __init__(
        self,
        rate_limit_config: RateLimitConfig | None = None,
        enable_audit_log: bool = True,
    ):
        self.prompt_guard = PromptGuard()
        self.rate_limiter = RateLimiter(rate_limit_config)
        self.audit_log = SecurityAuditLog() if enable_audit_log else None
    
    def check_input(
        self,
        text: str,
        source: str = "unknown",
        user_id: str | None = None,
        check_rate_limit: bool = True,
    ) -> "SecurityCheckResult":
        """
        Comprehensive input security check.
        
        Args:
            text: Input text to check
            source: Source of the input (e.g., "chat", "api", "skill")
            user_id: User identifier for rate limiting
            check_rate_limit: Whether to apply rate limiting
            
        Returns:
            SecurityCheckResult with analysis details
        """
        # Rate limiting
        if check_rate_limit and user_id:
            if not self.rate_limiter.is_allowed(user_id):
                if self.audit_log:
                    self.audit_log.log(
                        event_type="rate_limit",
                        severity=ThreatLevel.MEDIUM,
                        source=source,
                        details={"user_id": user_id},
                        blocked=True,
                    )
                return SecurityCheckResult(
                    allowed=False,
                    rejection_message="Rate limit exceeded. Please slow down.",
                    threat_level=ThreatLevel.MEDIUM,
                )
        
        # Prompt injection analysis
        injection_result = self.prompt_guard.analyze(text)
        
        if injection_result.blocked:
            if self.audit_log:
                self.audit_log.log(
                    event_type="prompt_injection",
                    severity=injection_result.threat_level,
                    source=source,
                    details={
                        "user_id": user_id,
                        "detections": injection_result.detections,
                        "input_preview": InputSanitizer.sanitize_for_logging(text, 200),
                    },
                    blocked=True,
                )
            return SecurityCheckResult(
                allowed=False,
                rejection_message="I detected potentially harmful patterns in your request. I can't process this.",
                threat_level=injection_result.threat_level,
                detections=injection_result.detections,
            )
        
        # SQL injection check
        sql_safe, sql_reason = InputSanitizer.check_sql_injection(text)
        if not sql_safe:
            if self.audit_log:
                self.audit_log.log(
                    event_type="sql_injection",
                    severity=ThreatLevel.HIGH,
                    source=source,
                    details={"user_id": user_id, "reason": sql_reason},
                    blocked=True,
                )
            return SecurityCheckResult(
                allowed=False,
                rejection_message="I detected potentially unsafe database patterns. Please rephrase your request.",
                threat_level=ThreatLevel.HIGH,
            )
        
        # Command injection check
        cmd_safe, cmd_reason = InputSanitizer.check_command_injection(text)
        if not cmd_safe:
            # Log but don't block - commands might be legitimate
            if self.audit_log:
                self.audit_log.log(
                    event_type="command_pattern",
                    severity=ThreatLevel.LOW,
                    source=source,
                    details={"user_id": user_id, "reason": cmd_reason},
                    blocked=False,
                )
        
        # Success - input is allowed
        if self.audit_log and injection_result.threat_level != ThreatLevel.NONE:
            # Log low-severity detections for monitoring
            self.audit_log.log(
                event_type="input_warning",
                severity=injection_result.threat_level,
                source=source,
                details={
                    "user_id": user_id,
                    "detections": injection_result.detections,
                },
                blocked=False,
            )
        
        return SecurityCheckResult(
            allowed=True,
            sanitized_input=injection_result.sanitized_input or text,
            threat_level=injection_result.threat_level,
            detections=injection_result.detections,
        )
    
    def filter_output(self, text: str, strict: bool = False) -> str:
        """Filter sensitive data from output."""
        return OutputFilter.filter_output(text, strict=strict)
    
    def get_security_summary(self, hours: int = 24) -> dict[str, Any]:
        """Get security event summary."""
        if self.audit_log:
            return self.audit_log.get_summary(hours)
        return {"error": "Audit logging disabled"}


@dataclass
class SecurityCheckResult:
    """Result of a security check."""
    allowed: bool
    rejection_message: str | None = None
    sanitized_input: str | None = None
    threat_level: ThreatLevel = ThreatLevel.NONE
    detections: list[dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Safe Database Query Builder
# =============================================================================

class SafeQueryBuilder:
    """
    Builds safe parameterized SQL queries.
    
    Prevents SQL injection by:
    - Using parameterized queries only
    - Validating table/column names against whitelist
    - Rejecting dangerous operations
    
    Usage:
        builder = SafeQueryBuilder(allowed_tables=["goals", "thoughts"])
        query, params = builder.select("goals", ["id", "title"], where={"status": "active"})
        # query = "SELECT id, title FROM goals WHERE status = $1"
        # params = ["active"]
    """
    
    DANGEROUS_KEYWORDS = {'DROP', 'TRUNCATE', 'ALTER', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE'}
    
    def __init__(
        self,
        allowed_tables: set[str] | None = None,
        allowed_columns: dict[str, set[str]] | None = None,
    ):
        self.allowed_tables = allowed_tables or set()
        self.allowed_columns = allowed_columns or {}
    
    def _validate_identifier(self, name: str, type_: str = "identifier") -> str:
        """Validate and sanitize an identifier."""
        clean = InputSanitizer.sanitize_identifier(name)
        if clean != name or not clean:
            raise ValueError(f"Invalid {type_}: {name}")
        return clean
    
    def _validate_table(self, table: str) -> str:
        """Validate table name."""
        table = self._validate_identifier(table, "table name")
        if self.allowed_tables and table not in self.allowed_tables:
            raise ValueError(f"Table not allowed: {table}")
        return table
    
    def _validate_column(self, table: str, column: str) -> str:
        """Validate column name."""
        column = self._validate_identifier(column, "column name")
        if table in self.allowed_columns:
            if column not in self.allowed_columns[table]:
                raise ValueError(f"Column not allowed: {table}.{column}")
        return column
    
    def select(
        self,
        table: str,
        columns: list[str],
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[str, list[Any]]:
        """
        Build a safe SELECT query.
        
        Returns:
            (query_string, parameters)
        """
        table = self._validate_table(table)
        cols = [self._validate_column(table, c) for c in columns]
        
        query = f"SELECT {', '.join(cols)} FROM {table}"
        params: list[Any] = []
        
        if where:
            conditions = []
            for i, (col, val) in enumerate(where.items(), 1):
                col = self._validate_column(table, col)
                conditions.append(f"{col} = ${i}")
                params.append(val)
            query += f" WHERE {' AND '.join(conditions)}"
        
        if order_by:
            order_col = self._validate_column(table, order_by.lstrip('-'))
            direction = "DESC" if order_by.startswith('-') else "ASC"
            query += f" ORDER BY {order_col} {direction}"
        
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        
        if offset is not None:
            query += f" OFFSET {int(offset)}"
        
        return query, params
    
    def insert(
        self,
        table: str,
        data: dict[str, Any],
        returning: list[str] | None = None,
    ) -> tuple[str, list[Any]]:
        """Build a safe INSERT query."""
        table = self._validate_table(table)
        
        cols = []
        placeholders = []
        params = []
        
        for i, (col, val) in enumerate(data.items(), 1):
            col = self._validate_column(table, col)
            cols.append(col)
            placeholders.append(f"${i}")
            params.append(val)
        
        query = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        
        if returning:
            ret_cols = [self._validate_column(table, c) for c in returning]
            query += f" RETURNING {', '.join(ret_cols)}"
        
        return query, params
    
    def update(
        self,
        table: str,
        data: dict[str, Any],
        where: dict[str, Any],
    ) -> tuple[str, list[Any]]:
        """Build a safe UPDATE query."""
        table = self._validate_table(table)
        
        if not where:
            raise ValueError("UPDATE requires WHERE clause for safety")
        
        sets = []
        params = []
        param_idx = 1
        
        for col, val in data.items():
            col = self._validate_column(table, col)
            sets.append(f"{col} = ${param_idx}")
            params.append(val)
            param_idx += 1
        
        conditions = []
        for col, val in where.items():
            col = self._validate_column(table, col)
            conditions.append(f"{col} = ${param_idx}")
            params.append(val)
            param_idx += 1
        
        query = f"UPDATE {table} SET {', '.join(sets)} WHERE {' AND '.join(conditions)}"
        
        return query, params


# =============================================================================
# Decorator for securing functions
# =============================================================================

F = TypeVar('F', bound=Callable)

def secure_input(
    security_gateway: AriaSecurityGateway | None = None,
    source: str = "function",
) -> Callable[[F], F]:
    """
    Decorator to secure function inputs.
    
    Usage:
        @secure_input(security, source="api")
        async def handle_message(text: str):
            ...
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get the first string argument as input
            text = None
            for arg in args:
                if isinstance(arg, str):
                    text = arg
                    break
            
            if text is None:
                text = kwargs.get('text') or kwargs.get('prompt') or kwargs.get('message')
            
            if text and security_gateway:
                result = security_gateway.check_input(text, source=source)
                if not result.allowed:
                    raise SecurityError(result.rejection_message or "Security check failed")
                
                # Replace with sanitized input
                if result.sanitized_input:
                    if args and isinstance(args[0], str):
                        args = (result.sanitized_input,) + args[1:]
                    elif 'text' in kwargs:
                        kwargs['text'] = result.sanitized_input
                    elif 'prompt' in kwargs:
                        kwargs['prompt'] = result.sanitized_input
                    elif 'message' in kwargs:
                        kwargs['message'] = result.sanitized_input
            
            return await func(*args, **kwargs)
        
        return wrapper  # type: ignore
    return decorator


class SecurityError(Exception):
    """Raised when a security check fails."""
    pass


# =============================================================================
# Convenience Instance
# =============================================================================

# Global security gateway instance
_default_gateway: AriaSecurityGateway | None = None


def get_security_gateway() -> AriaSecurityGateway:
    """Get or create the default security gateway."""
    global _default_gateway
    if _default_gateway is None:
        _default_gateway = AriaSecurityGateway()
    return _default_gateway


def check_input(text: str, source: str = "unknown", user_id: str | None = None) -> SecurityCheckResult:
    """Convenience function to check input security."""
    return get_security_gateway().check_input(text, source, user_id)


def filter_output(text: str, strict: bool = False) -> str:
    """Convenience function to filter output."""
    return get_security_gateway().filter_output(text, strict)
