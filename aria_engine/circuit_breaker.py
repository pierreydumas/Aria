"""
Generic Circuit Breaker — shared by LLMGateway and AriaSkill (S-22).

States:
    CLOSED  → requests flow normally; failures are counted
    OPEN    → requests are immediately rejected
    HALF-OPEN → after reset timeout, one probe request is allowed

Usage:
    cb = CircuitBreaker(name="llm", threshold=5, reset_after=30.0)

    if cb.is_open():
        raise SomeError("circuit open")

    try:
        result = await do_something()
        cb.record_success()
    except Exception:
        cb.record_failure()
        raise
"""
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("aria.engine.circuit_breaker")


class CircuitBreaker:
    """Thread-safe* circuit breaker with three states.

    * For asyncio single-threaded event loops; no locking needed.
    """

    __slots__ = (
        "name",
        "threshold",
        "reset_after",
        "_failures",
        "_opened_at",
        "_logger",
    )

    def __init__(
        self,
        name: str = "default",
        threshold: int = 5,
        reset_after: float = 30.0,
    ):
        self.name = name
        self.threshold = threshold
        self.reset_after = reset_after
        self._failures = 0
        self._opened_at: float | None = None
        self._logger = logger

    # ── State queries ────────────────────────────────────────────

    def is_open(self) -> bool:
        """Return True if the breaker is OPEN (reject requests)."""
        if self._failures < self.threshold:
            return False
        if self._opened_at is None:
            return False
        elapsed = time.monotonic() - self._opened_at
        if elapsed > self.reset_after:
            # Transition to HALF-OPEN — allow a probe request
            self._failures = 0
            self._opened_at = None
            self._logger.info(
                "Circuit breaker %s half-open after %.0fs — allowing probe",
                self.name,
                elapsed,
            )
            return False
        return True

    @property
    def state(self) -> str:
        """Return human-readable state: 'closed', 'open', or 'half-open'."""
        if self._failures < self.threshold:
            return "closed"
        if self._opened_at is not None:
            elapsed = time.monotonic() - self._opened_at
            if elapsed > self.reset_after:
                return "half-open"
        return "open"

    @property
    def failure_count(self) -> int:
        return self._failures

    # ── Outcome recording ────────────────────────────────────────

    def record_success(self) -> None:
        """Reset failure counter after a successful request."""
        self._failures = 0

    def record_failure(self) -> None:
        """Increment failure counter; open breaker when threshold reached."""
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()
            self._logger.warning(
                "Circuit breaker %s OPEN after %d consecutive failures",
                self.name,
                self._failures,
            )

    # ── Reset ────────────────────────────────────────────────────

    def spawn_gate(self) -> None:
        """Raise EngineError if this CB is OPEN, blocking sub-agent spawning.

        Call this before any sub-agent creation that would be used as a CB
        fallback path. Prevents cascade: if the CB that triggered the spawn
        decision is still OPEN, spawning another agent to retry is futile.

        Usage::

            cb.spawn_gate()              # raises EngineError if CB is open
            await pool.spawn_agent(...)  # only reached when CB is closed/half-open

        Raises:
            EngineError: When the circuit is OPEN.
        """
        if self.is_open():
            from aria_engine.exceptions import EngineError  # local import — avoids circular
            raise EngineError(
                f"Circuit breaker '{self.name}' is OPEN — "
                "spawning a sub-agent as fallback is blocked until the CB resets. "
                "Accept degraded state for this work cycle."
            )

    def reset(self) -> None:
        """Force-reset the circuit breaker to CLOSED state."""
        self._failures = 0
        self._opened_at = None

    # ── Persistence (aria_engine.circuit_breaker_state) ──────────

    async def persist(self, db: "AsyncEngine") -> None:
        """Upsert current state to ``aria_engine.circuit_breaker_state``.

        The in-memory hot-path is unchanged; call this after
        ``record_failure()`` / ``record_success()`` / ``reset()`` to make
        state durable across restarts.  Uses SQLAlchemy ORM — no raw SQL.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from db.models import EngineCircuitBreakerState

        # Convert monotonic offset → UTC wall-clock
        opened: datetime | None = None
        if self._opened_at is not None:
            wall = time.time() - time.monotonic() + self._opened_at
            opened = datetime.fromtimestamp(wall, tz=timezone.utc)

        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(EngineCircuitBreakerState)
            .values(
                name=self.name,
                failures=self._failures,
                opened_at=opened,
                state=self.state,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["name"],
                set_=dict(
                    failures=self._failures,
                    opened_at=opened,
                    state=self.state,
                    updated_at=now,
                ),
            )
        )
        async with db.begin() as conn:
            await conn.execute(stmt)

    @classmethod
    async def restore(
        cls,
        name: str,
        db: "AsyncEngine",
        threshold: int = 5,
        reset_after: float = 30.0,
    ) -> "CircuitBreaker":
        """Load a CircuitBreaker from persisted state, or return a fresh one.

        Uses ``aria_engine.circuit_breaker_state`` via SQLAlchemy ORM.
        If no row exists the returned breaker starts in CLOSED state.
        """
        from sqlalchemy import select

        from db.models import EngineCircuitBreakerState

        cb = cls(name=name, threshold=threshold, reset_after=reset_after)
        async with db.connect() as conn:
            result = await conn.execute(
                select(EngineCircuitBreakerState).where(
                    EngineCircuitBreakerState.name == name
                )
            )
            rec = result.mappings().first()

        if rec is None:
            return cb

        cb._failures = rec["failures"]
        if rec["opened_at"] is not None:
            # Convert UTC datetime back to a monotonic-equivalent float
            wall_offset = time.time() - time.monotonic()
            cb._opened_at = rec["opened_at"].timestamp() - wall_offset

        return cb

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(name={self.name!r}, state={self.state!r}, "
            f"failures={self._failures}/{self.threshold})"
        )
