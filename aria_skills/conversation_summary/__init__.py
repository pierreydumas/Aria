# aria_skills/conversation_summary/__init__.py
"""
📝 Conversation Summarization Skill

Compresses conversation history and activity logs into durable
semantic memories (episodic + decision categories).

Architecture: Skill (Layer 3) → api_client (Layer 2) → API (Layer 1)
Depends on S5-01 (pgvector semantic memory).
"""
import json
from typing import Any

from aria_skills.api_client import get_api_client
from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.litellm import LiteLLMSkill
from aria_skills.registry import SkillRegistry

try:
    from aria_models.loader import (
        get_primary_model as _get_primary_model,
        get_task_model as _get_task_model,
        normalize_temperature as _normalize_temperature,
    )
except ImportError:
    def _get_primary_model() -> str:
        return ""
    def _get_task_model(task: str) -> str:
        return ""
    def _normalize_temperature(model_id: str, temperature: float | None) -> float | None:
        return temperature

SUMMARIZATION_PROMPT = """\
Summarize this work session based on the activity log below. Respond ONLY with valid JSON.

Activity Log:
{activities}

Required JSON format:
{{
  "summary": "2-3 sentence summary of what happened",
  "decisions": ["decision 1", "decision 2"],
  "tone": "frustrated | satisfied | neutral | productive | exploratory",
  "unresolved": ["issue 1 still open"]
}}
"""

TOPIC_PROMPT = """\
Summarize everything known about the following topic based on these memory entries.
Respond ONLY with valid JSON.

Topic: {topic}

Memories:
{memories}

Required JSON format:
{{
  "summary": "Comprehensive 3-5 sentence summary",
  "key_facts": ["fact 1", "fact 2"],
  "open_questions": ["question 1"]
}}
"""


def _extract_message_text(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "".join(parts).strip()
    return ""


def _fallback_topic_summary(topic: str, memory_texts: list[str]) -> dict[str, Any]:
    facts = [text.removeprefix("- ").strip() for text in memory_texts[:3]]
    return {
        "summary": f"Synthesized {len(memory_texts)} memories about {topic}.",
        "key_facts": [fact for fact in facts if fact],
        "open_questions": [],
    }


@SkillRegistry.register
class ConversationSummarySkill(BaseSkill):
    """
    Summarizes conversations and activity sessions into
    durable semantic memories for long-term recall.
    """

    @property
    def name(self) -> str:
        return "conversation_summary"

    async def initialize(self) -> bool:
        """Initialize conversation summary skill."""
        self._api = await get_api_client()
        # S-115: Route LLM calls through litellm skill (no direct httpx)
        _llm_config = SkillConfig(name="litellm", config={})
        self._litellm = LiteLLMSkill(_llm_config)
        await self._litellm.initialize()
        self._status = SkillStatus.AVAILABLE
        self.logger.info("📝 Conversation summary skill initialized")
        return True

    async def close(self):
        if hasattr(self, "_litellm") and self._litellm:
            if hasattr(self._litellm, "_client") and self._litellm._client:
                await self._litellm._client.aclose()
            self._litellm = None
        self._api = None

    async def health_check(self) -> SkillStatus:
        return self._status

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @logged_method()
    async def summarize_session(
        self,
        hours_back: int = 24,
        session_id: str | None = None,
    ) -> SkillResult:
        """
        Summarize a recent work session.

        1. Fetches recent activities via the API
        2. Sends to LLM for summarization
        3. Stores summary as episodic SemanticMemory
        4. Stores each decision as decision SemanticMemory
        """
        try:
            result = await self._api.summarize_session(hours_back=hours_back)
            return SkillResult(
                success=True,
                data={"result": result, "info": f"Session summarized ({hours_back}h window)"},
            )
        except Exception as exc:
            self.logger.error("Session summarization failed: %s", exc)
            return SkillResult(
                success=False,
                data={"error": str(exc)},
                error=f"Summarization failed: {exc}",
            )

    @logged_method()
    async def summarize_topic(
        self,
        topic: str,
        max_memories: int = 20,
    ) -> SkillResult:
        """
        Summarize all memories related to a specific topic.

        1. Searches semantic memories by topic
        2. Sends matches to LLM for synthesis
        3. Stores synthesized summary as a new episodic memory
        """
        try:
            # Search for relevant memories
            search_results = await self._api.search_memories_semantic(
                query=topic,
                limit=max_memories,
            )
            # Handle both raw dict and SkillResult from api_client
            if hasattr(search_results, 'data'):
                raw = search_results.data
            else:
                raw = search_results
            if isinstance(raw, list):
                memories = raw
            elif isinstance(raw, dict):
                memories = raw.get("memories", raw.get("items", []))
            else:
                memories = []

            if not memories:
                return SkillResult(
                    success=True,
                    data={"summary": "No relevant memories found.", "key_facts": [], "open_questions": [], "info": f"No memories found for topic: {topic}"},
                )

            # Format memories for the prompt
            memory_texts = []
            for m in memories:
                content = m.get("content", "") if isinstance(m, dict) else str(m)
                memory_texts.append(f"- {content}")

            prompt = TOPIC_PROMPT.format(
                topic=topic,
                memories="\n".join(memory_texts),
            )

            # S-115: Route LLM calls through litellm skill (no direct httpx)
            summary_model = _get_task_model("conversation_summary") or _get_primary_model()
            fallback_model = _get_task_model("local_fast") or _get_primary_model()
            candidate_models = [summary_model]
            if fallback_model not in candidate_models:
                candidate_models.append(fallback_model)

            raw_text = ""
            last_error: Exception | None = None
            for candidate_model in candidate_models:
                llm_result = await self._litellm.chat_completion(
                    model=candidate_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=_normalize_temperature(candidate_model, 0.3) or 1.0,
                    max_tokens=1500,
                )
                if not llm_result.success:
                    last_error = Exception(llm_result.error or "LLM call failed")
                    continue

                llm_data = llm_result.data
                message = llm_data["choices"][0].get("message", {})
                raw_text = _extract_message_text(message)
                if raw_text:
                    break
                last_error = ValueError(
                    f"{candidate_model} returned empty content"
                )

            if not raw_text:
                parsed = _fallback_topic_summary(topic, memory_texts)
            else:
                try:
                    parsed = json.loads(raw_text)
                except json.JSONDecodeError:
                    parsed = _fallback_topic_summary(topic, memory_texts)

            # Store synthesis as a new episodic memory
            await self._api.store_memory_semantic(
                content=f"Topic synthesis — {topic}: {parsed.get('summary', raw_text)}",
                category="episodic",
                importance=0.7,
                source="conversation_summary",
            )

            return SkillResult(
                success=True,
                data=parsed,
            )

        except Exception as exc:
            self.logger.error("Topic summarization failed: %s", exc)
            return SkillResult(
                success=False,
                data={"error": str(exc)},
                error=f"Topic summarization failed: {exc}",
            )
