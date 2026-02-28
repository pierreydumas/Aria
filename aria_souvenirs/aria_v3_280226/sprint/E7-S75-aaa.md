# E7-S75 — Roundtable: Focus-Aware Agent Auto-Selection + Context Cap
**Epic:** E7 — Focus System v2 | **Priority:** P1 | **Points:** 5 | **Phase:** 3  
**Status:** NOT STARTED | **Depends on:** E7-S72 (SPECIALTY_PATTERNS DB-driven), E7-S73 (agents have _focus_profile)  
**Familiar Value:** Today Aria must enumerate agent IDs manually for every roundtable — "analyst, creator, devops" spelled out each time. This costs tokens AND requires Aria to know which agents are available. After this ticket, Aria says "discuss this devops issue" and the system auto-selects the right agents by keyword matching against the topic. This is the delegation hierarchy becoming self-organizing.

---

## Problem

**File:** `aria_engine/roundtable.py`

**Gap 1 — `discuss()` at line 136: `agent_ids` is required:**
```python
# aria_engine/roundtable.py line 136–145 (VERIFIED)
    async def discuss(
        self,
        topic: str,
        agent_ids: list[str],          # ← REQUIRED, always explicit
        rounds: int = DEFAULT_ROUNDS,
        synthesizer_id: str = "main",
        agent_timeout: int = DEFAULT_AGENT_TIMEOUT,
        total_timeout: int = DEFAULT_TOTAL_TIMEOUT,
        on_turn: Any = None,
    ) -> RoundtableResult:
```

Every roundtable caller must enumerate agents manually. There is no focus-based auto-selection. Aria's ORCHESTRATION.md (after S-79) says "if topic score > 0.5 in multiple domain, use roundtable" — but she can't act on this without knowing which agents to name.

**Gap 2 — `MAX_CONTEXT_TOKENS = 2000` at line 38: global constant, not per-agent:**
```python
# aria_engine/roundtable.py line 38 (VERIFIED)
MAX_CONTEXT_TOKENS = 2000   # Approx tokens to include from prior turns
```

A `social` agent with `token_budget_hint=800` receives 2000 tokens of discussion context — more than its entire response budget. The context alone exceeds its ceiling. This is a guaranteed budget-bust on every creative/social roundtable participation.

---

## Root Cause

`Roundtable` was built before focus profiles existed. `discuss()` is a low-level primitive that requires callers to know the agent roster. No layer between "trigger roundtable" and `discuss()` performs topic-based agent selection. `MAX_CONTEXT_TOKENS` was a reasonable default when all agents had similar budgets.

---

## Fix

### Step 1 — Make `agent_ids` optional + add `max_agents` cap

**File:** `aria_engine/roundtable.py`

**BEFORE (lines 136–145):**
```python
    async def discuss(
        self,
        topic: str,
        agent_ids: list[str],
        rounds: int = DEFAULT_ROUNDS,
        synthesizer_id: str = "main",
        agent_timeout: int = DEFAULT_AGENT_TIMEOUT,
        total_timeout: int = DEFAULT_TOTAL_TIMEOUT,
        on_turn: Any = None,
    ) -> RoundtableResult:
```

**AFTER:**
```python
    async def discuss(
        self,
        topic: str,
        agent_ids: list[str] | None = None,
        rounds: int = DEFAULT_ROUNDS,
        synthesizer_id: str = "main",
        agent_timeout: int = DEFAULT_AGENT_TIMEOUT,
        total_timeout: int = DEFAULT_TOTAL_TIMEOUT,
        on_turn: Any = None,
        max_agents: int = 5,     # hard cap — token economy enforcement
    ) -> RoundtableResult:
```

### Step 2 — Add auto-selection block at top of `discuss()` body

**Insert immediately after the docstring**, before the existing `if len(agent_ids) < 2:` guard:

```python
        # Auto-select agents if not explicitly provided
        if agent_ids is None:
            agent_ids = self._select_agents_for_topic(topic, max_agents)
            if len(agent_ids) < 2:
                raise EngineError(
                    f"Not enough agents available for roundtable on: '{topic[:80]}'"
                )

        # Enforce agent cap even for explicit lists — prevents accidental token explosion
        if len(agent_ids) > max_agents:
            logger.warning(
                "Roundtable: truncating %d→%d agents (max_agents=%d)",
                len(agent_ids), max_agents, max_agents,
            )
            agent_ids = agent_ids[:max_agents]
```

### Step 3 — Add `_select_agents_for_topic()` method

Add to `Roundtable` class (after `discuss()`, before `_run_round()`):

```python
    def _select_agents_for_topic(
        self,
        topic: str,
        max_agents: int = 5,
    ) -> list[str]:
        """
        Auto-select agents by focus keyword match against topic.

        Selection rules:
            1. Always include ≥1 L1 (orchestrator tier) agent by pheromone score
            2. Fill remaining slots with L2 agents scoring > 0.0 (sorted desc)
            3. Include L3 agents only if score > 0.4 AND slot available
            4. Hard cap at max_agents

        Returns:
            Ordered list of agent_ids (L1 first, then L2, then L3 by score).
        """
        from aria_engine.routing import compute_specialty_match

        try:
            all_agents = self._pool.list_agents()  # list[EngineAgent]
        except Exception as exc:
            logger.warning("_select_agents_for_topic: could not list agents: %s", exc)
            return []

        l1_entries, l2_entries, l3_entries = [], [], []

        for agent in all_agents:
            if getattr(agent, "status", "offline") in ("offline", "disabled", "error"):
                continue
            fp = getattr(agent, "_focus_profile", None)
            delegation_level = (fp.get("delegation_level") if fp else None) or 2
            score = compute_specialty_match(topic, agent.focus_type or "")

            entry = (agent.agent_id, score, delegation_level)
            if delegation_level == 1:
                l1_entries.append(entry)
            elif delegation_level == 2:
                l2_entries.append(entry)
            else:
                l3_entries.append(entry)

        # Sort by pheromone score (higher = better match) then by score
        l1_entries.sort(key=lambda x: x[1], reverse=True)
        l2_entries.sort(key=lambda x: x[1], reverse=True)
        l3_entries.sort(key=lambda x: x[1], reverse=True)

        selected: list[str] = []

        # Always include top L1 orchestrator if available
        if l1_entries:
            selected.append(l1_entries[0][0])

        # Fill L2 slots with scoring agents
        for agent_id, score, _ in l2_entries:
            if len(selected) >= max_agents:
                break
            if score > 0.0:
                selected.append(agent_id)

        # Include L3 only if score is high and slots remain
        for agent_id, score, _ in l3_entries:
            if len(selected) >= max_agents:
                break
            if score > 0.4:
                selected.append(agent_id)

        logger.debug(
            "_select_agents_for_topic: topic='%s' → selected=%s",
            topic[:60], selected,
        )
        return selected
```

### Step 4 — Dynamic context cap (replace global constant)

**File:** `aria_engine/roundtable.py`

**BEFORE (line 38):**
```python
MAX_CONTEXT_TOKENS = 2000   # Approx tokens to include from prior turns
```

**AFTER:**
```python
MAX_CONTEXT_TOKENS = 2000   # Default fallback — overridden dynamically per session
```

Find the location inside `_run_round()` or `_build_context()` where `MAX_CONTEXT_TOKENS` is used as the context window size. Add dynamic per-participant cap computation immediately before that usage:

```python
        # Compute dynamic context cap = min of all participants' token budgets
        # Ensures context never exceeds what the tightest-budget agent can receive
        participant_budgets = [
            agent._focus_profile.get("token_budget_hint", MAX_CONTEXT_TOKENS)
            for agent in participating_agents
            if getattr(agent, "_focus_profile", None)
        ]
        context_token_cap = min(participant_budgets) if participant_budgets else MAX_CONTEXT_TOKENS
```

**Note:** Before implementing Step 4, run:
```bash
grep -n "MAX_CONTEXT_TOKENS" aria_engine/roundtable.py
```
to find every usage site. Apply the dynamic cap to each consumption point.

---

## Constraints

| # | Constraint | Status | Notes |
|---|-----------|:------:|-------|
| 1 | Backward compatible | ✅ | `agent_ids=None` is the new default; existing callers passing explicit lists continue to work unchanged |
| 2 | Hard agent cap | ✅ | `max_agents=5` default — explicit calls also capped |
| 3 | Context cap per-participant | ✅ | `min(all budgets)` — no agent receives context exceeding its own ceiling |
| 4 | Graceful degradation | ✅ | Empty pool or DB failure → empty selection → EngineError with clear message |
| 5 | No soul files modified | ✅ | None |
| 6 | No circular imports | ✅ | `from aria_engine.routing import compute_specialty_match` inside method body |

---

## Dependencies

- **E7-S72 must complete first** — `compute_specialty_match()` must use DB-driven patterns and cover all 8 focus types
- **E7-S73 must complete first** — agents must have `_focus_profile` loaded for `delegation_level` and `token_budget_hint`

---

## Verification

```bash
# 1. Syntax clean
docker exec aria-engine python3 -c "
import ast, pathlib
ast.parse(pathlib.Path('aria_engine/roundtable.py').read_text())
print('syntax OK')
"
# EXPECTED: syntax OK

# 2. discuss() now accepts agent_ids=None
docker exec aria-engine python3 -c "
import inspect
from aria_engine.roundtable import Roundtable
sig = inspect.signature(Roundtable.discuss)
params = sig.parameters
print('agent_ids default:', params['agent_ids'].default)
print('max_agents default:', params['max_agents'].default)
assert params['agent_ids'].default is None
assert params['max_agents'].default == 5
print('PASS')
"
# EXPECTED: agent_ids default: None / max_agents default: 5 / PASS

# 3. _select_agents_for_topic() exists
docker exec aria-engine python3 -c "
from aria_engine.roundtable import Roundtable
assert hasattr(Roundtable, '_select_agents_for_topic')
print('_select_agents_for_topic method exists OK')
"
# EXPECTED: _select_agents_for_topic method exists OK

# 4. Agent cap truncates explicit lists
docker exec aria-engine python3 -c "
# Simulate the cap logic
agent_ids = ['a','b','c','d','e','f','g']
max_agents = 5
if len(agent_ids) > max_agents:
    agent_ids = agent_ids[:max_agents]
print('truncated to:', agent_ids)
assert len(agent_ids) == 5
print('PASS')
"
# EXPECTED: truncated to: ['a', 'b', 'c', 'd', 'e'] / PASS

# 5. MAX_CONTEXT_TOKENS still defined (do not remove — used as fallback)
docker exec aria-engine python3 -c "
from aria_engine.roundtable import MAX_CONTEXT_TOKENS
print('MAX_CONTEXT_TOKENS:', MAX_CONTEXT_TOKENS)
assert MAX_CONTEXT_TOKENS == 2000
print('PASS')
"
# EXPECTED: MAX_CONTEXT_TOKENS: 2000 / PASS
```

---

## Prompt for Agent

You are executing ticket **E7-S75** for the Aria project.

**Pre-check — confirm S72+S73 done:**
```bash
# S72: DB patterns loaded
docker exec aria-engine python3 -c "from aria_engine.routing import _FALLBACK_PATTERNS; print('S72 OK')"
# S73: _focus_profile field exists
docker exec aria-engine python3 -c "import dataclasses; from aria_engine.agent_pool import EngineAgent; assert '_focus_profile' in [f.name for f in dataclasses.fields(EngineAgent)]; print('S73 OK')"
```

**Constraint:** Backward compatible — explicit `agent_ids` lists must still work. `max_agents=5` is a hard cap, not advisory. `_select_agents_for_topic()` must never raise — return `[]` on any error and let the calling code raise `EngineError`.

**Files to read first:**
1. `aria_engine/roundtable.py` lines 136–175 — current `discuss()` signature and first guard block
2. `aria_engine/roundtable.py` lines 285–320 — find where `MAX_CONTEXT_TOKENS` is consumed
3. `aria_engine/roundtable.py` lines 98–130 — `Roundtable.__init__` to understand `self._pool` attribute name

**Steps:**
1. Change `discuss()` signature (Step 1).
2. Add auto-select + cap block at top of `discuss()` body (Step 2).
3. Add `_select_agents_for_topic()` method (Step 3).
4. Run `grep -n "MAX_CONTEXT_TOKENS" aria_engine/roundtable.py` to find all usage sites, then add dynamic cap (Step 4).
5. Run all 5 verification commands.
6. Report: "S-75 DONE — roundtable auto-selection active, context cap dynamic, all 5 verifications passed."
