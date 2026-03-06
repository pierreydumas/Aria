"""
Unit tests for aria_engine.session_isolation (T-06 — Audit).

Pure-Python subset: no DB queries invoked.
The conftest.py in this directory stubs ``db`` and ``sqlalchemy.ext.asyncio``
so all modules import cleanly.

Tests cover:
- AgentSessionScope stores the correct agent_id
- SessionIsolationFactory.for_agent() returns a scope with correct agent_id
- Factory caches scopes (same object returned for same agent_id)
- Factory returns distinct scopes for distinct agents
- Factory.list_scopes() reflects all created scopes
- Factory shares the same db_engine across scopes
- Scope created with config passes config through
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aria_engine.session_isolation import AgentSessionScope, SessionIsolationFactory


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_engine() -> MagicMock:
    """Return a minimal AsyncEngine mock."""
    engine = MagicMock()
    engine.connect = MagicMock()
    return engine


# ── AgentSessionScope ─────────────────────────────────────────────────────────


def test_scope_stores_agent_id():
    scope = AgentSessionScope("main", _mock_engine())
    assert scope.agent_id == "main"


def test_scope_different_agents_different_ids():
    scope_a = AgentSessionScope("aria-talk", _mock_engine())
    scope_b = AgentSessionScope("aria-analyst", _mock_engine())
    assert scope_a.agent_id != scope_b.agent_id


def test_scope_accepts_config():
    """AgentSessionScope should not raise when config is passed."""
    from aria_engine.config import EngineConfig
    cfg = EngineConfig()
    scope = AgentSessionScope("main", _mock_engine(), config=cfg)
    assert scope.agent_id == "main"
    assert scope._config is cfg


def test_scope_none_config_is_allowed():
    scope = AgentSessionScope("main", _mock_engine(), config=None)
    assert scope._config is None


# ── SessionIsolationFactory ───────────────────────────────────────────────────


def test_factory_for_agent_returns_scope():
    engine = _mock_engine()
    factory = SessionIsolationFactory(engine)
    scope = factory.for_agent("main")
    assert isinstance(scope, AgentSessionScope)
    assert scope.agent_id == "main"


def test_factory_caches_scope():
    """Calling for_agent twice with the same id returns the same object."""
    engine = _mock_engine()
    factory = SessionIsolationFactory(engine)
    scope_a = factory.for_agent("aria-talk")
    scope_b = factory.for_agent("aria-talk")
    assert scope_a is scope_b


def test_factory_distinct_agents_distinct_scopes():
    engine = _mock_engine()
    factory = SessionIsolationFactory(engine)
    scope_a = factory.for_agent("aria-talk")
    scope_b = factory.for_agent("aria-analyst")
    assert scope_a is not scope_b
    assert scope_a.agent_id != scope_b.agent_id


def test_factory_list_scopes_starts_empty():
    factory = SessionIsolationFactory(_mock_engine())
    assert factory.list_scopes() == []


def test_factory_list_scopes_reflects_created():
    factory = SessionIsolationFactory(_mock_engine())
    factory.for_agent("aria-talk")
    factory.for_agent("aria-analyst")
    factory.for_agent("main")
    scopes = factory.list_scopes()
    assert set(scopes) == {"aria-talk", "aria-analyst", "main"}
    assert len(scopes) == 3


def test_factory_scope_count_no_duplicates():
    factory = SessionIsolationFactory(_mock_engine())
    for _ in range(5):
        factory.for_agent("aria-talk")
    assert len(factory.list_scopes()) == 1


def test_factory_shares_db_engine():
    """All scopes created from the same factory use the same db engine."""
    engine = _mock_engine()
    factory = SessionIsolationFactory(engine)
    scope_a = factory.for_agent("aria-talk")
    scope_b = factory.for_agent("aria-analyst")
    assert scope_a._db_engine is scope_b._db_engine
    assert scope_a._db_engine is engine


def test_factory_with_config_passes_config_to_scopes():
    from aria_engine.config import EngineConfig
    engine = _mock_engine()
    cfg = EngineConfig()
    factory = SessionIsolationFactory(engine, config=cfg)
    scope = factory.for_agent("main")
    assert scope._config is cfg


# ── Isolation contract (structural) ──────────────────────────────────────────


def test_scopes_have_independent_agent_ids():
    """
    Structural test: confirms that two scopes from the same factory
    have different agent_id values — cross-agent leaking would mean
    they share the same id.
    """
    factory = SessionIsolationFactory(_mock_engine())
    agents = ["aria-talk", "aria-analyst", "aria-devops", "aria-creator", "main"]
    scopes = [factory.for_agent(a) for a in agents]
    ids = [s.agent_id for s in scopes]
    assert ids == agents, "Scopes must map 1:1 to agent IDs with no collisions"


def test_new_factory_creates_fresh_scope_for_same_agent():
    """
    Two different factory instances create independent scopes —
    caching is per-factory, not global.
    """
    engine = _mock_engine()
    factory_a = SessionIsolationFactory(engine)
    factory_b = SessionIsolationFactory(engine)
    scope_a = factory_a.for_agent("main")
    scope_b = factory_b.for_agent("main")
    # Both should have the same agent_id but be different objects
    assert scope_a.agent_id == scope_b.agent_id
    assert scope_a is not scope_b
