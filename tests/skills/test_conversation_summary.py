"""
Tests for the conversation_summary skill (Layer 3 — domain).

Covers:
- Initialization with mocked API + LiteLLM
- Session summarization (mocked API — workaround for SkillResult(message=) bug)
- Topic summarization with mocked LLM
- Empty conversation / no memories handling
- Error handling paths
- Close / cleanup

Previously the skill source had a bug where it passed ``message=`` to
``SkillResult()``, causing TypeError. That bug has been fixed — the skill now
uses the correct ``data=`` / ``error=`` fields.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aria_skills.base import SkillConfig, SkillResult, SkillStatus


# ---------------------------------------------------------------------------
# Helpers — patch both api_client and litellm at import time
# ---------------------------------------------------------------------------

def _build_mock_api():
    api = AsyncMock()
    api.summarize_session = AsyncMock(return_value={
        "summary": "Worked on CI tests",
        "decisions": ["Use pytest-asyncio"],
        "tone": "productive",
    })
    api.search_memories_semantic = AsyncMock(return_value=[
        {"content": "Aria uses a 3-tier memory system"},
        {"content": "LiteLLM is the LLM gateway"},
    ])
    api.store_memory_semantic = AsyncMock(return_value=SkillResult(
        success=True, data={"id": 42}
    ))
    return api


def _build_mock_litellm():
    llm = AsyncMock()
    llm.initialize = AsyncMock(return_value=True)
    llm._client = None
    llm.chat_completion = AsyncMock(return_value=SkillResult(
        success=True,
        data={
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "summary": "Aria uses hierarchical memory with LiteLLM as gateway.",
                        "key_facts": ["3-tier memory", "LiteLLM gateway"],
                        "open_questions": ["What about caching?"],
                    })
                }
            }]
        },
    ))
    return llm


async def _make_skill():
    """Create and initialize a ConversationSummarySkill with all deps mocked."""
    mock_api = _build_mock_api()
    mock_litellm = _build_mock_litellm()

    with patch("aria_skills.conversation_summary.get_api_client", new_callable=AsyncMock, return_value=mock_api), \
         patch("aria_skills.conversation_summary.LiteLLMSkill", return_value=mock_litellm):
        from aria_skills.conversation_summary import ConversationSummarySkill
        skill = ConversationSummarySkill(SkillConfig(name="conversation_summary"))
        await skill.initialize()
    return skill, mock_api, mock_litellm


# ---------------------------------------------------------------------------
# Tests — Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize():
    skill, _, _ = await _make_skill()
    assert await skill.health_check() == SkillStatus.AVAILABLE


# ---------------------------------------------------------------------------
# Tests — Session Summarization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summarize_session_calls_api():
    """summarize_session delegates to api.summarize_session."""
    skill, mock_api, _ = await _make_skill()
    result = await skill.summarize_session(hours_back=12)
    assert result.success is True
    mock_api.summarize_session.assert_awaited_once_with(hours_back=12)


@pytest.mark.asyncio
async def test_summarize_session_default_hours():
    skill, mock_api, _ = await _make_skill()
    result = await skill.summarize_session()
    assert result.success is True
    mock_api.summarize_session.assert_awaited_once_with(hours_back=24)


@pytest.mark.asyncio
async def test_summarize_session_api_error_returns_failure():
    """When api raises, the except handler returns a failure SkillResult."""
    skill, mock_api, _ = await _make_skill()
    mock_api.summarize_session.side_effect = RuntimeError("API down")
    result = await skill.summarize_session()
    assert result.success is False
    assert "API down" in (result.error or "")


# ---------------------------------------------------------------------------
# Tests — Topic Summarization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summarize_topic_no_memories():
    """No memories → fast-return with empty summary."""
    skill, mock_api, _ = await _make_skill()
    mock_api.search_memories_semantic.return_value = []
    result = await skill.summarize_topic(topic="unknown topic")
    assert result.success is True
    assert "No relevant memories" in result.data.get("summary", "")
    mock_api.search_memories_semantic.assert_awaited_once()


@pytest.mark.asyncio
async def test_summarize_topic_calls_llm():
    """With memories present the skill sends them to LLM for synthesis."""
    skill, mock_api, mock_llm = await _make_skill()
    result = await skill.summarize_topic(topic="memory architecture")
    assert result.success is True
    mock_api.search_memories_semantic.assert_awaited_once()
    mock_llm.chat_completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_summarize_topic_llm_failure():
    skill, mock_api, mock_llm = await _make_skill()
    mock_llm.chat_completion.return_value = SkillResult(success=False, error="LLM timeout")
    result = await skill.summarize_topic(topic="broken")
    assert result.success is False


# ---------------------------------------------------------------------------
# Tests — Close / Cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close():
    skill, _, _ = await _make_skill()
    await skill.close()
    assert skill._api is None
    assert skill._litellm is None


@pytest.mark.asyncio
async def test_close_without_litellm_client():
    skill, _, mock_llm = await _make_skill()
    mock_llm._client = None
    await skill.close()
    assert skill._litellm is None
