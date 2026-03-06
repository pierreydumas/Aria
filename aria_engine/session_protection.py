"""
Session Protection — rate limiting, validation, and concurrent write safety.

Features:
- Per-session rate limiting (sliding window)
- Per-agent rate limiting (aggregate cap)
- Message content validation (length, encoding, patterns)
- Session size limits (max messages per session)
- Advisory locking for concurrent write protection
- Input sanitization (strip control chars, validate encoding)
"""
import asyncio
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncEngine

from aria_engine.config import EngineConfig
from aria_engine.exceptions import EngineError
from db.models import EngineChatMessage

logger = logging.getLogger("aria.engine.session_protection")

# ── Rate Limiting ─────────────────────────────────────────────

# Sliding window config
DEFAULT_MAX_MESSAGES_PER_MINUTE = 20
DEFAULT_MAX_MESSAGES_PER_HOUR = 200
DEFAULT_MAX_MESSAGES_PER_SESSION = 500
AGENT_RATE_LIMITS = {
    "main": {"per_minute": 30, "per_hour": 300},
    "aria-talk": {"per_minute": 20, "per_hour": 200},
    "aria-analyst": {"per_minute": 15, "per_hour": 150},
    "aria-devops": {"per_minute": 15, "per_hour": 150},
    "aria-creator": {"per_minute": 15, "per_hour": 150},
    "aria-memeothy": {"per_minute": 10, "per_hour": 100},
}

# ── Validation ────────────────────────────────────────────────

MAX_MESSAGE_LENGTH = 100_000    # 100KB
MIN_MESSAGE_LENGTH = 1          # No empty messages
MAX_ROLE_LENGTH = 50
ALLOWED_ROLES = {"user", "assistant", "system", "tool", "function"}

# Control character pattern (except newline, tab, carriage return)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Prompt injection detection (basic patterns)
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a\s+)?(?:evil|jailbr)", re.I),
    re.compile(r"system\s*:\s*you\s+are", re.I),
    re.compile(r"\[INST\]|\[/INST\]|<\|im_start\|>", re.I),
]

# ── Errors ────────────────────────────────────────────────────


class RateLimitError(EngineError):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class ValidationError(EngineError):
    """Raised when message validation fails."""

    pass


class SessionFullError(EngineError):
    """Raised when session has reached max messages."""

    pass


# ── Data Classes ──────────────────────────────────────────────


@dataclass
class SlidingWindow:
    """Sliding window rate limiter for a single key.

    Timestamps are wall-clock POSIX floats (``time.time()``) so they can be
    serialised to ISO-8601 strings and persisted to
    ``aria_engine.rate_limit_windows`` via SQLAlchemy.
    """

    timestamps: list = field(default_factory=list)

    def add(self) -> None:
        """Record an event at the current wall-clock time."""
        self.timestamps.append(time.time())

    def count_in_window(self, window_seconds: float) -> int:
        cutoff = time.time() - window_seconds
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        return len(self.timestamps)

    def prune(self, max_age_seconds: float = 3600.0) -> None:
        """Drop timestamps older than *max_age_seconds*."""
        cutoff = time.time() - max_age_seconds
        self.timestamps = [t for t in self.timestamps if t > cutoff]

    def to_iso_list(self) -> list[str]:
        """Serialise to a list of ISO-8601 UTC strings for JSONB storage."""
        self.prune()
        return [
            datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
            for t in self.timestamps
        ]

    @classmethod
    def from_iso_list(cls, iso_list: list[str]) -> "SlidingWindow":
        """Rebuild a window from a persisted ISO list."""
        sw = cls()
        cutoff = time.time() - 3600.0
        for s in iso_list:
            try:
                ts = datetime.fromisoformat(s).timestamp()
                if ts > cutoff:
                    sw.timestamps.append(ts)
            except (ValueError, TypeError):
                pass
        return sw


class SessionProtection:
    """
    Session protection layer — validation, rate limiting, and locking.

    Wraps NativeSessionManager to enforce safety constraints.

    Usage:
        protector = SessionProtection(db_engine)

        # Validate and check rate limits before adding a message
        await protector.validate_and_check(
            session_id="abc123",
            agent_id="aria-talk",
            role="user",
            content="Hello there!",
        )
        # Raises RateLimitError, ValidationError, or SessionFullError

        # Acquire advisory lock for concurrent write safety
        async with protector.session_lock("abc123"):
            # Only one writer at a time
            await session_manager.add_message(...)
    """

    def __init__(
        self,
        db_engine: AsyncEngine,
        max_per_minute: int = DEFAULT_MAX_MESSAGES_PER_MINUTE,
        max_per_hour: int = DEFAULT_MAX_MESSAGES_PER_HOUR,
        max_per_session: int = DEFAULT_MAX_MESSAGES_PER_SESSION,
    ):
        self._db = db_engine
        self._max_per_minute = max_per_minute
        self._max_per_hour = max_per_hour
        self._max_per_session = max_per_session

        # In-memory rate limiters (per session + per agent)
        # Timestamps are wall-clock so they survive serialisation to PG.
        self._session_windows: dict[str, SlidingWindow] = defaultdict(
            SlidingWindow
        )
        self._agent_windows: dict[str, SlidingWindow] = defaultdict(
            SlidingWindow
        )

        # Advisory lock set (track which sessions are locked)
        self._locks: dict[str, asyncio.Lock] = {}

    # ── Persistence (aria_engine.rate_limit_windows) ──────────────

    async def load_windows(self) -> None:
        """Hydrate in-memory windows from ``aria_engine.rate_limit_windows``.

        Call once after process start to restore rate-limit state across
        restarts.  Uses SQLAlchemy ORM — no raw SQL.
        """
        from db.models import EngineRateLimitWindow

        async with self._db.connect() as conn:
            result = await conn.execute(select(EngineRateLimitWindow))
            rows = result.mappings().all()

        for row in rows:
            window = SlidingWindow.from_iso_list(row["events"] or [])
            if not window.timestamps:
                continue
            if row["window_type"] == "session":
                self._session_windows[row["window_key"]] = window
            elif row["window_type"] == "agent":
                self._agent_windows[row["window_key"]] = window

        logger.debug("Loaded %d persisted rate-limit windows", len(rows))

    async def _save_window(
        self,
        window_key: str,
        window_type: str,
        window: SlidingWindow,
    ) -> None:
        """Upsert one sliding window to ``aria_engine.rate_limit_windows``.

        Fire-and-forget — callers use ``asyncio.create_task`` around this.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from db.models import EngineRateLimitWindow

        iso_events = window.to_iso_list()
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(EngineRateLimitWindow)
            .values(
                window_key=window_key,
                window_type=window_type,
                events=iso_events,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_rlw_key_type",
                set_=dict(events=iso_events, updated_at=now),
            )
        )
        try:
            async with self._db.begin() as conn:
                await conn.execute(stmt)
        except Exception:
            logger.debug(
                "rate_limit_windows persist failed for %s/%s",
                window_type,
                window_key,
            )

    async def validate_and_check(
        self,
        session_id: str,
        agent_id: str,
        role: str,
        content: str,
    ) -> str:
        """
        Validate message and check rate limits.

        Performs all safety checks before a message is added:
        1. Content validation (length, encoding, role)
        2. Input sanitization (strip control chars)
        3. Prompt injection detection (log but don't block)
        4. Rate limiting (per-session and per-agent)
        5. Session size check (max messages)

        Args:
            session_id: Target session.
            agent_id: Agent handling the message.
            role: Message role.
            content: Message content.

        Returns:
            Sanitized content string.

        Raises:
            ValidationError: If content or role is invalid.
            RateLimitError: If rate limit exceeded.
            SessionFullError: If session is at max capacity.
        """
        # 1. Validate role
        if role not in ALLOWED_ROLES:
            raise ValidationError(
                f"Invalid role: {role}. Allowed: {ALLOWED_ROLES}"
            )
        if len(role) > MAX_ROLE_LENGTH:
            raise ValidationError(
                f"Role too long: {len(role)} > {MAX_ROLE_LENGTH}"
            )

        # 2. Validate content length
        if len(content) < MIN_MESSAGE_LENGTH:
            raise ValidationError("Message content is empty")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValidationError(
                f"Message too long: {len(content)} > {MAX_MESSAGE_LENGTH}"
            )

        # 3. Sanitize content
        content = self.sanitize_content(content)

        # 4. Check prompt injection (log only, don't block)
        self._check_injection(content, session_id, agent_id)

        # 5. Rate limiting — per session
        session_window = self._session_windows[session_id]
        minute_count = session_window.count_in_window(60)
        if minute_count >= self._max_per_minute:
            raise RateLimitError(
                f"Rate limit exceeded for session {session_id}: "
                f"{minute_count}/{self._max_per_minute} per minute",
                retry_after=30,
            )

        hour_count = session_window.count_in_window(3600)
        if hour_count >= self._max_per_hour:
            raise RateLimitError(
                f"Rate limit exceeded for session {session_id}: "
                f"{hour_count}/{self._max_per_hour} per hour",
                retry_after=300,
            )

        # 6. Rate limiting — per agent (aggregate across sessions)
        agent_limits = AGENT_RATE_LIMITS.get(
            agent_id,
            {
                "per_minute": self._max_per_minute,
                "per_hour": self._max_per_hour,
            },
        )
        agent_window = self._agent_windows[agent_id]
        agent_minute = agent_window.count_in_window(60)
        if agent_minute >= agent_limits["per_minute"]:
            raise RateLimitError(
                f"Agent {agent_id} rate limit: "
                f"{agent_minute}/{agent_limits['per_minute']} per minute",
                retry_after=30,
            )

        # 7. Session size check
        msg_count = await self._get_session_message_count(session_id)
        if msg_count >= self._max_per_session:
            raise SessionFullError(
                f"Session {session_id} is full: "
                f"{msg_count}/{self._max_per_session} messages"
            )

        # Record the request in rate limiter windows
        session_window.add()
        agent_window.add()

        # Fire-and-forget persistence to aria_engine.rate_limit_windows
        asyncio.create_task(
            self._save_window(session_id, "session", session_window),
            name=f"rlw-session-{session_id[:8]}",
        )
        asyncio.create_task(
            self._save_window(agent_id, "agent", agent_window),
            name=f"rlw-agent-{agent_id}",
        )

        return content

    def sanitize_content(self, content: str) -> str:
        """
        Sanitize message content.

        - Strip control characters (except \\n, \\t, \\r)
        - Normalize whitespace
        - Ensure valid UTF-8
        """
        # Remove control characters
        content = CONTROL_CHAR_RE.sub("", content)

        # Strip leading/trailing whitespace
        content = content.strip()

        # Ensure valid UTF-8 (replace invalid bytes)
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")

        return content

    def _check_injection(
        self,
        content: str,
        session_id: str,
        agent_id: str,
    ) -> None:
        """
        Check for prompt injection patterns.

        Logs a warning but does not block — human review recommended.
        """
        for pattern in INJECTION_PATTERNS:
            if pattern.search(content):
                logger.warning(
                    "Potential prompt injection detected in "
                    "session=%s agent=%s: matched pattern '%s'",
                    session_id,
                    agent_id,
                    pattern.pattern[:50],
                )
                return  # Log only once per message

    async def _get_session_message_count(
        self,
        session_id: str,
    ) -> int:
        """Get current message count for a session."""
        async with self._db.begin() as conn:
            result = await conn.execute(
                select(func.count())
                .select_from(EngineChatMessage)
                .where(EngineChatMessage.session_id == session_id)
            )
            return result.scalar() or 0

    def session_lock(self, session_id: str) -> "SessionLock":
        """
        Get an advisory lock for a session.

        Usage:
            async with protector.session_lock("abc123"):
                await mgr.add_message(...)
        """
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return SessionLock(self._locks[session_id])

    def cleanup_windows(self, max_age_seconds: int = 7200) -> int:
        """
        Clean up stale in-memory rate limiter windows.

        Should be called periodically to prevent memory leaks.
        DB rows keep their own TTL via ``to_iso_list()`` pruning on every
        write — this only cleans the in-process dict.

        Returns:
            Number of windows cleaned up.
        """
        cleaned = 0

        for key in list(self._session_windows.keys()):
            window = self._session_windows[key]
            window.prune(max_age_seconds)
            if not window.timestamps:
                del self._session_windows[key]
                cleaned += 1

        for key in list(self._agent_windows.keys()):
            window = self._agent_windows[key]
            window.prune(max_age_seconds)
            if not window.timestamps:
                del self._agent_windows[key]
                cleaned += 1

        if cleaned:
            logger.debug("Cleaned %d stale rate limit windows", cleaned)

        return cleaned

    def get_rate_limit_status(
        self,
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Get current rate limit status for monitoring."""
        status: dict[str, Any] = {}

        if session_id and session_id in self._session_windows:
            w = self._session_windows[session_id]
            status["session"] = {
                "per_minute": w.count_in_window(60),
                "per_hour": w.count_in_window(3600),
                "limit_per_minute": self._max_per_minute,
                "limit_per_hour": self._max_per_hour,
            }

        if agent_id and agent_id in self._agent_windows:
            limits = AGENT_RATE_LIMITS.get(
                agent_id,
                {
                    "per_minute": self._max_per_minute,
                    "per_hour": self._max_per_hour,
                },
            )
            w = self._agent_windows[agent_id]
            status["agent"] = {
                "per_minute": w.count_in_window(60),
                "per_hour": w.count_in_window(3600),
                "limit_per_minute": limits["per_minute"],
                "limit_per_hour": limits["per_hour"],
            }

        return status


class SessionLock:
    """
    Async context manager for session advisory locking.

    Uses asyncio.Lock for in-process safety. For multi-process,
    can be extended to use PostgreSQL advisory locks.
    """

    def __init__(self, lock: asyncio.Lock):
        self._lock = lock

    async def __aenter__(self):
        await self._lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()
        return False
