"""
Sprint 7 — Atomic unit tests for cognition, focus, memory, and heartbeat features.

Tests each SP7 ticket independently with mocked dependencies.
Run: pytest tests/test_sprint7_cognition.py -v
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_soul():
    """Minimal Soul mock."""
    soul = MagicMock()
    soul.name = "Aria Blue"
    soul.identity = MagicMock()
    soul.identity.name = "Aria Blue"
    soul.identity.vibe = "electric & curious"
    soul.check_request.return_value = (True, "")
    soul.get_system_prompt.return_value = "You are Aria Blue."
    soul._loaded = True
    # Focus manager mock
    fm = MagicMock()
    fm.active = MagicMock()
    fm.active.type = MagicMock(value="orchestrator")
    fm.active.get_system_prompt_overlay.return_value = ""
    fm.get_focus_for_task.return_value = MagicMock(value="devsecops")
    fm.set_focus = MagicMock()
    soul.focus_manager = fm
    return soul


def _make_memory():
    """Minimal MemoryManager mock."""
    mem = MagicMock()
    mem._connected = True
    mem.remember_short = MagicMock()
    mem.flag_important = MagicMock()
    mem.recall_short.return_value = [
        {"category": "user_input", "content": "hello"},
    ]
    mem.log_thought = AsyncMock()
    mem.get_recent_thoughts = AsyncMock(return_value=[])
    mem.record_retrieval_quality = MagicMock()
    return mem


def _make_llm_skill(response_text="Test LLM response"):
    """LLMSkill mock with complete() that returns OpenAI-style response."""
    llm = MagicMock()
    llm.is_available = True

    result = MagicMock()
    result.success = True
    result.data = {
        "choices": [
            {"message": {"content": response_text}}
        ],
        "_aria_model_used": "litellm/qwen3.5_mlx",
    }
    llm.complete = AsyncMock(return_value=result)
    return llm


def _make_api_client_skill(semantic_memories=None):
    """api_client skill mock with search_memories_semantic."""
    api = MagicMock()
    api.is_available = True

    if semantic_memories is None:
        semantic_memories = [
            {"id": "mem-1", "content": "Python deployment uses Docker containers", "importance": 0.7},
            {"id": "mem-2", "content": "Always check circuit breakers before retrying", "importance": 0.5},
        ]

    sem_result = MagicMock()
    sem_result.success = True
    sem_result.data = semantic_memories
    api.search_memories_semantic = AsyncMock(return_value=sem_result)

    api.store_sentiment_event = AsyncMock()
    return api


def _make_skill_registry(llm=None, api=None):
    """SkillRegistry mock."""
    registry = MagicMock()
    skills = {}
    if llm:
        skills["llm"] = llm
    if api:
        skills["api_client"] = api
    registry.get = lambda name: skills.get(name)
    registry.list.return_value = list(skills.keys())
    return registry


def _make_agent_coordinator(response_text="Agent response"):
    """AgentCoordinator mock."""
    coord = MagicMock()
    resp = MagicMock()
    resp.content = response_text
    coord.process = AsyncMock(return_value=resp)
    coord.list_agents.return_value = ["aria", "explorer"]
    return coord


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def soul():
    return _make_soul()


@pytest.fixture
def memory():
    return _make_memory()


@pytest.fixture
def llm_skill():
    return _make_llm_skill()


@pytest.fixture
def api_skill():
    return _make_api_client_skill()


# ── SP7-02: Metacognition Strategy Routing ──────────────────────────────────

class TestSP702MetacognitionRouting:
    """Verify cognition.process() consults metacognition for strategy."""

    @pytest.mark.asyncio
    async def test_metacognition_strategy_injected_into_context(self, soul, memory, llm_skill):
        """Strategy from metacognition should appear in context passed to agents."""
        from aria_mind.cognition import Cognition

        agents = _make_agent_coordinator()
        registry = _make_skill_registry(llm=llm_skill)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        with patch("aria_mind.metacognition.get_metacognitive_engine") as mock_mc:
            engine = MagicMock()
            engine.get_strategy_for_category.return_value = {
                "approach": "explore_first",
                "confidence": 0.7,
                "max_retries": 3,
                "use_roundtable": False,
            }
            engine.predict_outcome.return_value = {
                "predicted_success": 0.8,
                "risk_factors": [],
                "recommendation": "proceed",
            }
            engine._category_strategies = {"general": {"approach": "explore_first"}}
            engine.record_task = MagicMock()
            mock_mc.return_value = engine

            result = await cog.process("deploy the new API version")

            # Strategy should have been consulted
            engine.get_strategy_for_category.assert_called()
            engine.predict_outcome.assert_called()

    @pytest.mark.asyncio
    async def test_roundtable_route_when_strategy_recommends(self, soul, memory, llm_skill):
        """When metacognition says use_roundtable=True, cognition routes to roundtable."""
        from aria_mind.cognition import Cognition

        agents = _make_agent_coordinator()
        agents.roundtable = AsyncMock(return_value=MagicMock(content="Roundtable result"))
        registry = _make_skill_registry(llm=llm_skill)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        with patch("aria_mind.metacognition.get_metacognitive_engine") as mock_mc:
            engine = MagicMock()
            engine.get_strategy_for_category.return_value = {
                "approach": "roundtable",
                "confidence": 0.9,
                "max_retries": 2,
                "use_roundtable": True,
            }
            engine.predict_outcome.return_value = {"predicted_success": 0.9}
            engine._category_strategies = {}
            engine.record_task = MagicMock()
            mock_mc.return_value = engine

            result = await cog.process("complex multi-agent task")

            agents.roundtable.assert_called_once()
            assert "Roundtable result" in result


# ── SP7-03: PEVR Loop ──────────────────────────────────────────────────────

class TestSP703PEVRLoop:
    """Verify plan_execute_verify_reflect works end-to-end."""

    @pytest.mark.asyncio
    async def test_pevr_produces_plan_and_results(self, soul, memory):
        """PEVR should plan, execute steps, verify, and reflect."""
        from aria_mind.cognition import Cognition

        agents = _make_agent_coordinator("Step executed successfully")
        registry = _make_skill_registry(llm=_make_llm_skill("1. Research\n2. Implement\n3. Test"))
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        result = await cog.plan_execute_verify_reflect("Build a REST API endpoint")

        assert "plan" in result
        assert "step_results" in result
        assert "overall_success" in result
        assert "reflection" in result
        assert len(result["step_results"]) > 0

    @pytest.mark.asyncio
    async def test_pevr_aborts_after_3_failures(self, soul, memory):
        """PEVR should abort early if 3+ steps fail."""
        from aria_mind.cognition import Cognition

        agents = _make_agent_coordinator("[Error: everything broke]")
        registry = _make_skill_registry(llm=_make_llm_skill("1. Do A\n2. Do B\n3. Do C\n4. Do D\n5. Do E"))
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        result = await cog.plan_execute_verify_reflect("Impossible task")

        assert result["failures"] >= 3
        assert result["overall_success"] is False
        # Should not have tried all 5 steps
        assert len(result["step_results"]) < 5

    @pytest.mark.asyncio
    async def test_pevr_records_metacognitive_outcome(self, soul, memory):
        """PEVR should record outcome in metacognition."""
        from aria_mind.cognition import Cognition

        agents = _make_agent_coordinator("Done")
        registry = _make_skill_registry(llm=_make_llm_skill("1. Execute task"))
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        result = await cog.plan_execute_verify_reflect("Simple task")

        # Should have adjusted confidence
        assert cog._total_processed == 0  # PEVR uses _record_outcome directly
        # Either success or failure was tracked
        assert (cog._total_successes + cog._total_failures) >= 1


# ── SP7-04 + SP7-07: Focus Auto-Switching (LLM + keyword) ──────────────────

class TestSP707FocusClassification:
    """Verify focus classification uses llm.complete() with correct API."""

    @pytest.mark.asyncio
    async def test_classify_focus_llm_calls_complete(self):
        """classify_focus_llm should call llm_skill.complete() not generate()."""
        from aria_mind.soul.focus import FocusManager, FocusType

        fm = FocusManager.__new__(FocusManager)
        llm = _make_llm_skill("devsecops")
        result = await fm.classify_focus_llm("deploy the docker containers", llm_skill=llm)

        # Should have called complete(), not generate()
        llm.complete.assert_called_once()
        assert not hasattr(llm, "generate") or not getattr(llm.generate, "called", False)

        # Should pass messages format
        call_kwargs = llm.complete.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0]
        assert isinstance(messages, list)
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_classify_focus_llm_passes_temperature(self):
        """Focus classification should pass temperature=0.1, max_tokens=32."""
        from aria_mind.soul.focus import FocusManager

        fm = FocusManager.__new__(FocusManager)
        llm = _make_llm_skill("orchestrator")
        await fm.classify_focus_llm("manage the team workflow", llm_skill=llm)

        call_kwargs = llm.complete.call_args.kwargs
        assert call_kwargs.get("temperature") == 0.1
        assert call_kwargs.get("max_tokens") == 32

    @pytest.mark.asyncio
    async def test_classify_focus_llm_parses_response(self):
        """Should parse FocusType from LLM response."""
        from aria_mind.soul.focus import FocusManager, FocusType

        fm = FocusManager.__new__(FocusManager)
        llm = _make_llm_skill("devsecops")
        result = await fm.classify_focus_llm("fix the CI pipeline", llm_skill=llm)

        assert result == FocusType.DEVSECOPS

    @pytest.mark.asyncio
    async def test_classify_focus_llm_falls_back_on_failure(self):
        """If LLM fails, should fall back to keyword matching."""
        from aria_mind.soul.focus import FocusManager

        fm = FocusManager.__new__(FocusManager)
        # Mock get_focus_for_task for fallback
        fm.get_focus_for_task = MagicMock(return_value=MagicMock(value="orchestrator"))

        llm = MagicMock()
        llm.complete = AsyncMock(side_effect=Exception("LLM down"))

        result = await fm.classify_focus_llm("something", llm_skill=llm)

        fm.get_focus_for_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_classify_focus_llm_no_skill_falls_back(self):
        """If no LLM skill, should fall back to keyword matching."""
        from aria_mind.soul.focus import FocusManager

        fm = FocusManager.__new__(FocusManager)
        fm.get_focus_for_task = MagicMock(return_value=MagicMock(value="creative"))

        result = await fm.classify_focus_llm("write a poem", llm_skill=None)

        fm.get_focus_for_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_cognition_process_reads_focus_without_switching(self, soul, memory):
        """cognition.process() should read current focus but NOT auto-switch it."""
        from aria_mind.cognition import Cognition

        llm = _make_llm_skill("devsecops")
        agents = _make_agent_coordinator()
        registry = _make_skill_registry(llm=llm)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        await cog.process("deploy the docker image to production")

        # Focus should NOT be auto-switched — Aria decides her own focus
        assert not soul.focus_manager.set_focus.called


# ── SP7-05: Semantic Memory Recall ──────────────────────────────────────────

class TestSP705SemanticMemoryRecall:
    """Verify semantic memory recall fires in cognition.process()."""

    @pytest.mark.asyncio
    async def test_semantic_recall_calls_api_client(self, soul, memory):
        """process() should call api_client.search_memories_semantic."""
        from aria_mind.cognition import Cognition

        api = _make_api_client_skill()
        llm = _make_llm_skill()
        agents = _make_agent_coordinator()
        registry = _make_skill_registry(llm=llm, api=api)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        await cog.process("how do I deploy with docker?")

        api.search_memories_semantic.assert_called_once()
        call_kwargs = api.search_memories_semantic.call_args.kwargs
        assert "query" in call_kwargs
        assert call_kwargs.get("limit") == 5
        assert call_kwargs.get("min_importance") == 0.3

    @pytest.mark.asyncio
    async def test_semantic_recall_tags_memories(self, soul, memory):
        """Retrieved semantic memories should be tagged with _retrieved_for."""
        from aria_mind.cognition import Cognition

        memories = [
            {"id": "m1", "content": "Docker uses containers", "importance": 0.8},
        ]
        api = _make_api_client_skill(semantic_memories=memories)
        agents = _make_agent_coordinator()
        registry = _make_skill_registry(llm=_make_llm_skill(), api=api)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        # We need to inspect the context that gets passed
        original_process = agents.process

        captured_context = {}

        async def capture_process(prompt, **ctx):
            captured_context.update(ctx)
            return (await original_process(prompt, **ctx))

        agents.process = capture_process

        await cog.process("docker containers")

        # Check semantic memories were injected
        assert "semantic_memory" in captured_context
        assert captured_context["semantic_memory"][0]["_retrieved_for"] is not None

    @pytest.mark.asyncio
    async def test_semantic_recall_skipped_if_no_api(self, soul, memory):
        """If api_client not available, semantic recall silently skips."""
        from aria_mind.cognition import Cognition

        agents = _make_agent_coordinator()
        registry = _make_skill_registry(llm=_make_llm_skill())
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        # Should not raise
        result = await cog.process("test without api")
        assert result is not None


# ── SP7-08: Memory Quality Feedback ─────────────────────────────────────────

class TestSP708MemoryQualityFeedback:
    """Verify memory quality tracking after process()."""

    @pytest.mark.asyncio
    async def test_quality_tracking_called(self, soul, memory):
        """record_retrieval_quality should be called for retrieved memories."""
        from aria_mind.cognition import Cognition

        # Set up memories that overlap with the response
        memories = [
            {"id": "m1", "content": "Docker containers are isolated environments", "importance": 0.8},
            {"id": "m2", "content": "Unrelated trivia about cats", "importance": 0.3},
        ]
        api = _make_api_client_skill(semantic_memories=memories)
        # Agent response mentions "docker" and "containers"
        agents = _make_agent_coordinator("Docker containers are great for deployment and isolation")
        registry = _make_skill_registry(llm=_make_llm_skill(), api=api)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        await cog.process("tell me about docker")

        # record_retrieval_quality should have been called for each memory
        assert memory.record_retrieval_quality.call_count == 2

    @pytest.mark.asyncio
    async def test_quality_tracking_identifies_used_memories(self, soul, memory):
        """Memories with token overlap should be marked as used=True."""
        from aria_mind.cognition import Cognition

        memories = [
            {"id": "m1", "content": "Docker containers provide isolation and portability", "importance": 0.8},
            {"id": "m2", "content": "Butterflies migrate thousands of miles", "importance": 0.3},
        ]
        api = _make_api_client_skill(semantic_memories=memories)
        agents = _make_agent_coordinator("Docker containers provide excellent isolation for services")
        registry = _make_skill_registry(llm=_make_llm_skill(), api=api)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry, agent_coordinator=agents)

        await cog.process("docker question")

        # First memory (docker containers isolation) should be was_used=True
        calls = memory.record_retrieval_quality.call_args_list
        # Find the call for m1 and m2
        m1_call = [c for c in calls if c.kwargs.get("memory_id") == "m1" or (c.args and c.args[0] == "m1")]
        m2_call = [c for c in calls if c.kwargs.get("memory_id") == "m2" or (c.args and c.args[0] == "m2")]

        if m1_call:
            assert m1_call[0].kwargs.get("was_used") is True
        if m2_call:
            assert m2_call[0].kwargs.get("was_used") is False


# ── SP7-02+03: LLM complete() API (not generate()) ─────────────────────────

class TestLLMCompleteAPI:
    """Verify all LLM calls use complete(messages=) not generate(prompt=)."""

    @pytest.mark.asyncio
    async def test_fallback_process_uses_complete(self, soul, memory):
        """_fallback_process should call llm.complete(messages=...)."""
        from aria_mind.cognition import Cognition

        llm = _make_llm_skill("Fallback response")
        registry = _make_skill_registry(llm=llm)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry)

        result = await cog._fallback_process("test prompt", {"system_prompt": "Be helpful"})

        llm.complete.assert_called_once()
        call_kwargs = llm.complete.call_args.kwargs
        messages = call_kwargs.get("messages")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Be helpful"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "test prompt"

    @pytest.mark.asyncio
    async def test_fallback_process_extracts_content(self, soul, memory):
        """_fallback_process should extract content from OpenAI-style response."""
        from aria_mind.cognition import Cognition

        llm = _make_llm_skill("The answer is 42")
        registry = _make_skill_registry(llm=llm)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry)

        result = await cog._fallback_process("what is the answer?", {})

        assert result == "The answer is 42"

    @pytest.mark.asyncio
    async def test_reflect_uses_complete(self, soul, memory):
        """reflect() should call llm.complete(messages=...) when agents fail."""
        from aria_mind.cognition import Cognition

        llm = _make_llm_skill("I notice patterns of growth in recent tasks.")
        registry = _make_skill_registry(llm=llm)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry)

        # Add some data for reflection
        memory.recall_short.return_value = [
            {"category": "user_input", "content": "deploy the app"},
            {"category": "goal_work", "content": "building CI pipeline"},
        ]

        result = await cog.reflect()

        # LLM should have been called with complete()
        llm.complete.assert_called_once()
        call_kwargs = llm.complete.call_args.kwargs
        assert "messages" in call_kwargs
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 2048
        assert "patterns" in result.lower() or "growth" in result.lower()

    @pytest.mark.asyncio
    async def test_plan_uses_complete(self, soul, memory):
        """plan() should call llm.complete(messages=...) when agents unavailable."""
        from aria_mind.cognition import Cognition

        llm = _make_llm_skill("1. Research the problem\n2. Design the solution\n3. Implement it")
        registry = _make_skill_registry(llm=llm)
        cog = Cognition(soul=soul, memory=memory, skill_registry=registry)

        steps = await cog.plan("Build a notification system")

        llm.complete.assert_called_once()
        call_kwargs = llm.complete.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 1024
        assert len(steps) == 3
        assert "Research" in steps[0]
