"""
Context Window Manager — Sliding window with importance-based eviction.

Builds an optimal message list within a token budget by:
1. Always including: system prompt, first user message (establishes identity)
2. Always including: last N messages (recent context)
3. Scoring middle messages by importance and keeping highest-scored within budget
4. Token counting via litellm.token_counter (model-aware)

The goal: maximize context quality within the token budget.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

from aria_engine.config import EngineConfig

logger = logging.getLogger("aria.engine.context")


# ── Importance scores by role ─────────────────────────────────────────────────
# Higher = more important to keep in context
IMPORTANCE_SCORES: dict[str, int] = {
    "system": 100,
    "tool": 80,
    "user": 60,
    "assistant": 40,
}

# Minimum number of recent messages to always include (tail)
MIN_RECENT_MESSAGES = 4

# Fallback tokens-per-message estimate when counting fails
FALLBACK_TOKENS_PER_MESSAGE = 150


@dataclass
class ScoredMessage:
    """A message with its importance score and token count."""
    index: int
    message: dict[str, Any]
    role: str
    tokens: int
    importance: int
    is_pinned: bool = False  # pinned = must include (system, first msg, recent)

    @property
    def priority(self) -> tuple[bool, int, int]:
        """Sort key: pinned first, then by importance, then by recency (index)."""
        return (self.is_pinned, self.importance, self.index)


class ContextManager:
    """
    Manages the conversation context window with token-aware eviction.

    Usage:
        ctx = ContextManager(config)

        # Build context from raw message list:
        messages = ctx.build_context(
            all_messages=full_history,
            max_tokens=8192,
            model="qwen3-30b-mlx",
        )

        # Or build from DB session:
        messages = await ctx.build_context_from_session(
            db=db_session,
            session_id=session_id,
            system_prompt="You are Aria...",
            max_tokens=8192,
            model="qwen3-30b-mlx",
        )
    """

    def __init__(self, config: EngineConfig):
        self.config = config

    def build_context(
        self,
        all_messages: list[dict[str, Any]],
        max_tokens: int = 8192,
        model: str = "",
        reserve_tokens: int = 1024,
    ) -> list[dict[str, Any]]:
        """
        Build an optimal message list within the token budget.

        Args:
            all_messages: Full conversation history (list of {role, content, ...}).
            max_tokens: Maximum tokens allowed for the context window.
            model: Model name for accurate token counting.
            reserve_tokens: Tokens reserved for the model's response.

        Returns:
            Filtered and ordered list of messages fitting within the budget.
        """
        if not all_messages:
            return []

        budget = max_tokens - reserve_tokens
        if budget <= 0:
            logger.warning("Token budget <= 0 after reserve. Returning system prompt only.")
            return [m for m in all_messages if m.get("role") == "system"][:1]

        # ── Score and tokenize all messages ───────────────────────────────
        scored: list[ScoredMessage] = []
        for i, msg in enumerate(all_messages):
            role = msg.get("role", "user")
            tokens = self._count_tokens(msg, model)
            importance = self._compute_importance(msg, i, len(all_messages))
            is_pinned = self._is_pinned(msg, i, len(all_messages))

            scored.append(ScoredMessage(
                index=i,
                message=msg,
                role=role,
                tokens=tokens,
                importance=importance,
                is_pinned=is_pinned,
            ))

        # ── Phase 1: Always include pinned messages ───────────────────────
        pinned = [s for s in scored if s.is_pinned]
        unpinned = [s for s in scored if not s.is_pinned]

        pinned_tokens = sum(s.tokens for s in pinned)

        if pinned_tokens >= budget:
            # Even pinned messages exceed budget — include what fits
            logger.warning(
                "Pinned messages (%d tokens) exceed budget (%d). Truncating.",
                pinned_tokens, budget,
            )
            result: list[ScoredMessage] = []
            used = 0
            for s in pinned:
                if used + s.tokens <= budget:
                    result.append(s)
                    used += s.tokens
                else:
                    break
            result.sort(key=lambda s: s.index)
            return [s.message for s in result]

        # ── Phase 2: Fill remaining budget with highest-importance unpinned ─
        remaining_budget = budget - pinned_tokens
        unpinned.sort(key=lambda s: (s.importance, s.index), reverse=True)

        selected_unpinned: list[ScoredMessage] = []
        used_unpinned = 0
        for s in unpinned:
            if used_unpinned + s.tokens <= remaining_budget:
                selected_unpinned.append(s)
                used_unpinned += s.tokens

        # ── Phase 3: Combine and sort by original order ───────────────────
        final = pinned + selected_unpinned
        final.sort(key=lambda s: s.index)

        total_tokens = sum(s.tokens for s in final)
        logger.debug(
            "Context: %d/%d messages, %d/%d tokens (budget=%d, reserve=%d)",
            len(final), len(all_messages), total_tokens, max_tokens,
            budget, reserve_tokens,
        )

        return [s.message for s in final]

    async def build_context_from_session(
        self,
        db,
        session_id,
        system_prompt: str | None = None,
        max_tokens: int = 8192,
        model: str = "",
        reserve_tokens: int = 1024,
        max_messages: int = 200,
    ) -> list[dict[str, Any]]:
        """
        Build context by loading messages from the database.

        Args:
            db: AsyncSession instance.
            session_id: UUID of the session.
            system_prompt: System prompt to prepend (if not already in DB).
            max_tokens: Token budget.
            model: Model for token counting.
            reserve_tokens: Tokens reserved for response.
            max_messages: Maximum messages to load from DB.

        Returns:
            Optimized message list.
        """
        from db.models import EngineChatMessage
        from sqlalchemy import select

        result = await db.execute(
            select(EngineChatMessage)
            .where(EngineChatMessage.session_id == session_id)
            .order_by(EngineChatMessage.created_at.asc())
            .limit(max_messages)
        )
        rows = result.scalars().all()

        all_messages: list[dict[str, Any]] = []

        # Prepend system prompt if provided
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})

        # Convert DB rows to message dicts
        for row in rows:
            msg: dict[str, Any] = {"role": row.role, "content": row.content}
            if row.tool_calls:
                msg["tool_calls"] = row.tool_calls
            if row.role == "tool" and row.tool_results:
                msg["tool_call_id"] = row.tool_results.get("tool_call_id", "")
            all_messages.append(msg)

        return self.build_context(
            all_messages=all_messages,
            max_tokens=max_tokens,
            model=model,
            reserve_tokens=reserve_tokens,
        )

    def _count_tokens(self, message: dict[str, Any], model: str) -> int:
        """
        Count tokens in a message using litellm's token counter.

        Falls back to a rough estimate if litellm fails.
        """
        try:
            from litellm import token_counter
            # litellm.token_counter expects a list of messages
            count = token_counter(model=model, messages=[message])
            return count
        except Exception:
            # Fallback: rough estimate (4 chars ≈ 1 token)
            content = message.get("content", "")
            if isinstance(content, str):
                return max(len(content) // 4, 1)
            return FALLBACK_TOKENS_PER_MESSAGE

    def _compute_importance(
        self, message: dict[str, Any], index: int, total: int
    ) -> int:
        """
        Compute importance score for a message.

        Factors:
        - Role-based base score (system=100, tool=80, user=60, assistant=40)
        - Boost for messages with tool_calls or tool results (+20)
        - Boost for longer messages that contain substantive content (+10)
        - Recency boost for messages in the last quarter (+15)
        """
        role = message.get("role", "user")
        score = IMPORTANCE_SCORES.get(role, 30)

        # Boost tool-related messages (they carry execution context)
        if message.get("tool_calls") or message.get("tool_call_id"):
            score += 20

        # Boost substantive messages (>200 chars)
        content = message.get("content", "")
        if isinstance(content, str) and len(content) > 200:
            score += 10

        # Recency boost: last quarter of conversation gets +15
        if total > 0 and index >= total * 0.75:
            score += 15

        return score

    def _is_pinned(self, message: dict[str, Any], index: int, total: int) -> bool:
        """
        Determine if a message must always be included.

        Pinned messages:
        - System prompt (role=system)
        - First user message (establishes identity/topic)
        - Last MIN_RECENT_MESSAGES messages (recent context)
        """
        role = message.get("role", "user")

        # System prompts are always pinned
        if role == "system":
            return True

        # First user message (establishes the conversation topic)
        if index == 0 or (index == 1 and role == "user"):
            return True

        # Last N messages are always pinned
        if total > 0 and index >= total - MIN_RECENT_MESSAGES:
            return True

        return False

    def estimate_tokens(
        self, messages: list[dict[str, Any]], model: str = ""
    ) -> int:
        """
        Estimate total tokens for a list of messages.

        Useful for checking whether a context fits before sending to LLM.
        """
        return sum(self._count_tokens(m, model) for m in messages)

    def get_window_stats(
        self, all_messages: list[dict[str, Any]], model: str = ""
    ) -> dict[str, Any]:
        """
        Get statistics about the context window.

        Returns:
            Dict with total_messages, total_tokens, role_breakdown, etc.
        """
        role_counts: dict[str, int] = {}
        role_tokens: dict[str, int] = {}
        total_tokens = 0

        for msg in all_messages:
            role = msg.get("role", "unknown")
            tokens = self._count_tokens(msg, model)
            total_tokens += tokens
            role_counts[role] = role_counts.get(role, 0) + 1
            role_tokens[role] = role_tokens.get(role, 0) + tokens

        return {
            "total_messages": len(all_messages),
            "total_tokens": total_tokens,
            "role_counts": role_counts,
            "role_tokens": role_tokens,
        }
