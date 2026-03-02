# aria_skills/base.py
"""
Base classes for Aria skills.

Enhanced with:
- Retry logic via tenacity
- Metrics collection for observability
- Structured logging support
"""
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from typing import Any, Callable, TypeVar

from aria_engine.circuit_breaker import CircuitBreaker

# Optional imports for enhanced features
try:
    from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
    HAS_TENACITY = True
except ImportError:
    HAS_TENACITY = False

try:
    import structlog
    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False

try:
    from prometheus_client import Counter, Histogram, Gauge
    HAS_PROMETHEUS = True
    
    # Prometheus metrics for skills
    SKILL_CALLS = Counter(
        'aria_skill_calls_total',
        'Total skill invocations',
        ['skill', 'function', 'status']
    )
    SKILL_LATENCY = Histogram(
        'aria_skill_latency_seconds',
        'Skill execution latency',
        ['skill', 'function'],
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
    )
    SKILL_ERRORS = Counter(
        'aria_skill_errors_total',
        'Total skill errors',
        ['skill', 'error_type']
    )
except ImportError:
    HAS_PROMETHEUS = False

# In-process skill health dashboard (lightweight aggregator for cognition)
try:
    from aria_mind.skill_health_dashboard import record_skill_execution as _record_dashboard_metric
    HAS_HEALTH_DASHBOARD = True
except ImportError:
    HAS_HEALTH_DASHBOARD = False

logger = logging.getLogger(__name__)

T = TypeVar('T')


class SkillStatus(Enum):
    """Skill availability status."""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


@dataclass
class SkillConfig:
    """Configuration for a skill."""
    name: str
    enabled: bool = True
    config: dict = field(default_factory=dict)
    rate_limit: dict | None = None
    
    @classmethod
    def from_dict(cls, data: dict) -> "SkillConfig":
        return cls(
            name=data.get("skill", data.get("name", "unknown")),
            enabled=data.get("enabled", True),
            config=data.get("config", {}),
            rate_limit=data.get("rate_limit"),
        )


@dataclass
class SkillResult:
    """Result from a skill operation."""
    success: bool
    data: Any = None
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @classmethod
    def ok(cls, data: Any = None) -> "SkillResult":
        return cls(success=True, data=data)
    
    @classmethod
    def fail(cls, error: str) -> "SkillResult":
        return cls(success=False, error=error)

    def __bool__(self) -> bool:
        return self.success


class BaseSkill(ABC):
    """
    Abstract base class for all skills.
    
    Skills must implement:
    - name: Unique skill identifier
    - initialize(): Setup and validation
    - health_check(): Verify availability
    """
    
    def __init__(self, config: SkillConfig):
        self.config = config
        self.logger = logging.getLogger(f"aria.skills.{self.name}")
        self._status = SkillStatus.UNAVAILABLE
        self._last_used: datetime | None = None
        self._use_count = 0
        self._error_count = 0
        # Circuit breaker (shared module — S-22)
        self._cb = CircuitBreaker(
            name=f"skill-{self.name}",
            threshold=5,
            reset_after=60.0,
        )
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill identifier."""
        pass

    @property
    def canonical_name(self) -> str:
        """Kebab-case canonical name with aria- prefix for cross-system lookup."""
        return f"aria-{self.name.replace('_', '-')}"
    
    @abstractmethod
    async def initialize(self) -> bool:
        """
        Initialize the skill.
        Validate configuration, test connections, etc.
        
        Returns:
            True if initialization successful
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> SkillStatus:
        """
        Check if skill is available and healthy.
        
        Returns:
            Current skill status
        """
        pass
    
    @property
    def is_available(self) -> bool:
        """Check if skill is available for use."""
        return self._status == SkillStatus.AVAILABLE
    
    @property
    def status(self) -> SkillStatus:
        """Current skill status."""
        return self._status
    
    def _log_usage(self, operation: str, success: bool, **kwargs):
        """Log skill usage with structured data."""
        self._last_used = datetime.now(timezone.utc)
        self._use_count += 1
        if not success:
            self._error_count += 1
        
        log_data = {
            "skill": self.name,
            "operation": operation,
            "success": success,
            "use_count": self._use_count,
            "error_count": self._error_count,
            **kwargs
        }
        
        if success:
            self.logger.info(f"Skill {self.name}.{operation} completed", extra=log_data)
        else:
            self.logger.warning(f"Skill {self.name}.{operation} failed", extra=log_data)
    
    def _get_env_value(self, key: str) -> str | None:
        """
        Get value from config, resolving env: prefix.
        
        Args:
            key: Config key to look up
            
        Returns:
            Resolved value or None
        """
        import os
        
        value = self.config.config.get(key)
        if value and isinstance(value, str) and value.startswith("env:"):
            env_var = value[4:]  # Remove "env:" prefix
            return os.environ.get(env_var)
        return value
    
    def get_metrics(self, **kwargs) -> dict:
        """Get skill usage metrics."""
        return {
            "name": self.name,
            "status": self._status.value,
            "last_used": self._last_used.isoformat() if self._last_used else None,
            "use_count": self._use_count,
            "error_count": self._error_count,
            "error_rate": self._error_count / max(self._use_count, 1),
            "avg_latency_ms": getattr(self, '_avg_latency_ms', 0),
        }
    
    async def execute_with_retry(
        self, 
        func: Callable[..., T], 
        *args, 
        max_attempts: int = 3,
        **kwargs
    ) -> T:
        """
        Execute a function with automatic retry on transient failures.
        Checks lessons_learned for known resolutions before retrying (S5-02).
        
        Args:
            func: The async function to execute
            *args: Positional arguments for func
            max_attempts: Maximum retry attempts (default: 3)
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func
            
        Raises:
            Exception: If all retries fail
        """
        if HAS_TENACITY:
            @retry(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                reraise=True
            )
            async def _retry_wrapper():
                return await func(*args, **kwargs)
            
            try:
                return await _retry_wrapper()
            except Exception as e:
                await self._handle_error(e)
                raise
        else:
            # Fallback without tenacity
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        import asyncio
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
            await self._handle_error(last_error)
            raise last_error

    async def _handle_error(self, error: Exception):
        """Check lessons_learned for known resolutions (S5-02)."""
        try:
            from aria_skills.api_client import get_api_client
            client = await get_api_client()
            error_type = type(error).__name__

            lessons = await client.check_known_errors(
                error_type=error_type, skill_name=self.name
            )
            if lessons.success and lessons.data.get("has_resolution"):
                resolution = lessons.data["lessons"][0].get("resolution", "")
                self.logger.info(
                    f"Known error pattern found. Resolution: {resolution}"
                )
            else:
                # Record new error for future learning
                await client.record_lesson(
                    error_pattern=f"{self.name}_{error_type}",
                    error_type=error_type,
                    resolution="unresolved — needs investigation",
                    skill_name=self.name,
                )
        except Exception as e:
            self.logger.debug("Error lesson recording failed: %s", e)
    
    async def execute_with_metrics(
        self, 
        func: Callable[..., T], 
        operation_name: str,
        *args, 
        **kwargs
    ) -> T:
        """
        Execute a function while collecting metrics.
        
        Args:
            func: The async function to execute
            operation_name: Name for metrics labeling
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func
        """
        start_time = time.time()
        success = False
        error_type = None
        
        try:
            result = await func(*args, **kwargs)
            success = True
            return result
        except Exception as e:
            error_type = type(e).__name__
            raise
        finally:
            latency = time.time() - start_time
            latency_ms = latency * 1000
            
            # Update internal metrics
            self._use_count += 1
            self._last_used = datetime.now(timezone.utc)
            if not success:
                self._error_count += 1
            
            # Update rolling average latency
            if not hasattr(self, '_avg_latency_ms'):
                self._avg_latency_ms = 0
            self._avg_latency_ms = (
                (self._avg_latency_ms * (self._use_count - 1) + latency_ms) 
                / self._use_count
            )
            
            # Record skill invocation via API (S5-07)
            if self.name != "api_client":
                try:
                    from aria_skills.api_client import get_api_client
                    import asyncio
                    client = await get_api_client()
                    asyncio.ensure_future(
                        client.record_invocation(
                            skill_name=self.name,
                            tool_name=operation_name,
                            duration_ms=int(latency_ms),
                            success=success,
                            error_type=error_type,
                        )
                    )
                except Exception as e:
                    self.logger.debug("Metrics recording failed: %s", e)
            
            # In-process health dashboard (for cognition-level routing)
            if HAS_HEALTH_DASHBOARD:
                try:
                    _record_dashboard_metric(
                        skill_name=self.name,
                        execution_time_ms=latency_ms,
                        success=success,
                        error_type=error_type,
                    )
                except Exception as e:
                    self.logger.debug("Dashboard metric failed: %s", e)

            # Prometheus metrics
            if HAS_PROMETHEUS:
                SKILL_CALLS.labels(
                    skill=self.name,
                    function=operation_name,
                    status='success' if success else 'error'
                ).inc()
                SKILL_LATENCY.labels(
                    skill=self.name,
                    function=operation_name
                ).observe(latency)
                if error_type:
                    SKILL_ERRORS.labels(
                        skill=self.name,
                        error_type=error_type
                    ).inc()
            
            # Structured logging
            log_data = {
                "skill": self.name,
                "operation": operation_name,
                "success": success,
                "latency_ms": round(latency_ms, 2),
            }
            if error_type:
                log_data["error_type"] = error_type
            
            if HAS_STRUCTLOG:
                structlog.get_logger().info("skill_execution", **log_data)
            else:
                self.logger.info(f"skill_execution: {log_data}")
    
    # ── Circuit Breaker ─────────────────────────────────────────
    def _is_cb_open(self) -> bool:
        """Check if this skill's circuit breaker is open."""
        return self._cb.is_open()

    def _cb_record_success(self):
        self._cb.record_success()

    def _cb_record_failure(self):
        self._cb.record_failure()

    async def safe_execute(
        self,
        func: Callable[..., T],
        operation_name: str,
        *args,
        with_retry: bool = True,
        max_attempts: int = 3,
        **kwargs
    ) -> T:
        """
        Execute a function with both retry logic and metrics collection.
        
        This is the recommended way to call external services.
        
        Args:
            func: The async function to execute
            operation_name: Name for metrics/logging
            *args: Positional arguments for func
            with_retry: Whether to use retry logic (default: True)
            max_attempts: Max retry attempts if retry enabled
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func
        """
        async def _wrapped():
            if self._is_cb_open():
                raise RuntimeError(f"Circuit breaker open for skill {self.name}")
            try:
                if with_retry:
                    result = await self.execute_with_retry(
                        func, *args, max_attempts=max_attempts, **kwargs
                    )
                else:
                    result = await func(*args, **kwargs)
                self._cb_record_success()
                return result
            except Exception:
                self._cb_record_failure()
                raise
        
        return await self.execute_with_metrics(_wrapped, operation_name)

    async def _log_activity(self, action: str, details: str = "", success: bool = True):
        """Log activity to database via fire-and-forget. Non-blocking."""
        try:
            import asyncio
            # Use create_task for fire-and-forget
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._write_activity_log(action, details, success))
        except Exception as e:
            self.logger.debug("Activity log scheduling failed: %s", e)

    async def _write_activity_log(self, action: str, details: str, success: bool):
        """Actually write to activity log. Called as background task."""
        try:
            from aria_skills.api_client import get_api_client
            client = await get_api_client()
            await client.create_activity(
                action=action,
                skill=self.name,
                details={"message": details} if details else {},
                success=success,
            )
        except Exception as e:
            self.logger.debug(f"Activity log write failed (non-critical): {e}")


# ── Activity Logging Decorator ──────────────────────────────────────────
import functools
import time as _time

def logged_method(action_name: str = None):
    """
    Decorator that logs skill method calls to activity_log via aria-api.
    
    Usage:
        @logged_method()
        async def my_method(self, ...):
            ...
        
        @logged_method("custom.action.name")
        async def my_method(self, ...):
            ...
    
    The decorator:
    - Records start/end time, duration_ms
    - POSTs to /activities endpoint via httpx (fire-and-forget)
    - Skips logging for api_client skill (recursion guard)
    - Never blocks or breaks the wrapped method
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            op_name = action_name or f"{self.name}.{func.__name__}"
            start = _time.monotonic()
            try:
                result = await func(self, *args, **kwargs)
                duration_ms = int((_time.monotonic() - start) * 1000)
                if self.name != "api_client":
                    import asyncio
                    asyncio.ensure_future(_post_activity(
                        action=op_name, skill=self.name,
                        details={"method": func.__name__, "duration_ms": duration_ms},
                        success=True,
                    ))
                return result
            except Exception as e:
                duration_ms = int((_time.monotonic() - start) * 1000)
                if self.name != "api_client":
                    import asyncio
                    asyncio.ensure_future(_post_activity(
                        action=op_name, skill=self.name,
                        details={"method": func.__name__, "duration_ms": duration_ms},
                        success=False, error_message=str(e)[:500],
                    ))
                raise
        return wrapper
    return decorator


_activity_client = None

async def _post_activity(action, skill, details, success, error_message=None):
    """Fire-and-forget POST to /activities. Never raises."""
    global _activity_client
    try:
        import httpx
        import os
        if _activity_client is None:
            api_url = os.environ.get("ARIA_API_URL", "http://aria-api:8000")
            _activity_client = httpx.AsyncClient(base_url=api_url, timeout=5.0)
        await _activity_client.post("/activities", json={
            "action": action,
            "skill": skill,
            "details": details,
            "success": success,
            "error_message": error_message,
        })
    except Exception as e:
        logger.debug("Activity POST failed: %s", e)
