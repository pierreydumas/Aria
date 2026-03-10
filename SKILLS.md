# Aria Blue ⚡️ — Skill System

## What Is a Skill?

A skill is a self-contained module that gives Aria a specific capability. Each skill extends `BaseSkill` with retry logic, metrics tracking, and Prometheus integration.

Skills are Aria's **hands** — they execute actions in the world (API calls, database queries, content posting, health checks, security scans).

---

## 5-Layer Hierarchy

Skills are organized in a strict layer hierarchy. Lower layers never import from higher layers. **All database access flows through Layer 1.**

| Layer | Purpose | Examples |
|-------|---------|----------|
| **0 — Kernel** | Read-only identity & security | `input_guard` |
| **1 — API Client** | Sole database gateway | `api_client` |
| **2 — Core** | Essential runtime services | `health`, `litellm`, `model_switcher`, `moonshot`, `ollama`, `session_manager` |
| **3 — Domain** | Feature-specific skills | `research`, `moltbook`, `social`, `market_data`, `goals`, `agent_manager`, `working_memory`, `sandbox` |
| **4 — Orchestration** | Planning & scheduling | `schedule`, `hourly_goals`, `performance`, `pipeline_skill` |

The architecture rule is enforced by `tests/check_architecture.py` — run it before every PR merge.

---

## Skill Structure

Every skill lives in `aria_skills/<skill_name>/` with at minimum:

```
aria_skills/<skill>/
├── __init__.py      # Skill class extending BaseSkill
├── skill.json       # Manifest (layer, tools, dependencies)
└── SKILL.md         # Documentation (optional)
```

### BaseSkill Framework

| Component | Description |
|-----------|-------------|
| `SkillStatus` | `AVAILABLE`, `UNAVAILABLE`, `RATE_LIMITED`, `ERROR` |
| `SkillConfig` | `name`, `enabled`, `config`, optional `rate_limit` |
| `SkillResult` | `success`, `data`, `error`, `timestamp` — factories `.ok()` / `.fail()` |
| `BaseSkill` | Abstract base with metrics, retry, Prometheus integration |

### Registry

Skills are auto-discovered by the `SkillRegistry` via the `@SkillRegistry.register` decorator. The registry provides `get(name)`, `list_available()`, and `check_all_health()`.

---

## Creating a New Skill

Read the full specification and step-by-step guide:

- [Skill Standard](aria_skills/SKILL_STANDARD.md) — naming, structure, required class methods
- [Skill Creation Guide](aria_skills/SKILL_CREATION_GUIDE.md) — walkthrough with examples
- [Skill Template](aria_skills/_template/) — scaffold for new skills

---

## Self-Healing Error Recovery

Aria's resilience is built in four phases across the Skills layer.

### Phase 1 — API Client Circuit Breaker (pre-sprint)
- `aria_skills/api_client/__init__.py` has `_is_circuit_open()`, `_record_failure()`, `_record_success()`, `_request_with_retry()` with exponential backoff + jitter.
- Generic HTTP verbs `get`, `post`, `patch`, `put`, `delete` call `_request_with_retry`.

### Phase 2 — All Endpoint Methods Use Retry (S-45)
- **All 112 specific endpoint methods** (e.g. `create_activity`, `get_goals`, `create_heartbeat`) now delegate to `self._request_with_retry()` — zero methods bypass the retry/circuit-breaker.
- `get_memory()` handles 404 via exception inspection instead of status-code branch.
- Invariant: `grep "self._client.(get|post|patch|put|delete)" aria_skills/api_client/__init__.py` → 0 matches.

### Phase 3 — LLM Fallback Chain (S-45)
- `aria_skills/llm/__init__.py` — `LLMSkill` — new skill.
- `LLM_FALLBACK_CHAIN` priority list: `litellm/qwen3.5_mlx` (local) → `litellm/trinity` (free) → `litellm/kimi` (paid).
- `complete_with_fallback(messages)` iterates chain, skips open circuits, records success/failure per model.
- `complete(messages, model=None)` pins to a specific model with auto-fallback on failure.
- `get_circuit_status()` returns live per-model circuit state.

### Phase 4 — Health Degradation Levels (S-45)
- `aria_skills/health/__init__.py` — `HealthDegradationLevel` enum added: `HEALTHY`, `DEGRADED`, `CRITICAL`, `RECOVERY`.
- `check_degradation_level()` counts failing subsystems; 0 → HEALTHY, 1-2 → DEGRADED, 3+ → CRITICAL.
- `apply_degradation_mode(level)` returns suspension plan: DEGRADED suspends `moltbook_check`, `social_post`; CRITICAL also suspends `research_cycle`, `brainstorm`, `goal_check`, `agent_audit`; `heartbeat` and `health_check` are **never** suspended.

### Phase 5 — Chaos Tests (S-45)
- `tests/test_self_healing.py` — 6 tests: circuit opens after threshold, exponential backoff verified, LLM fallback skips open circuit, `create_activity` resilient to 1 transient failure, degradation level detection, apply_degradation_mode job suspension matrix.

---

## Source of Truth

The live skill catalog is the `aria_skills/` directory itself. Each `skill.json` manifest declares the skill's layer, dependencies, and tool schemas. Do not maintain a hardcoded list elsewhere.

To list all registered skills at runtime:

```bash
python -m aria_mind --list-skills
```

Or browse: `aria_skills/*/skill.json`

---

## Related

- [ARCHITECTURE.md](ARCHITECTURE.md) — Layer diagram, data flow, and enforcement rules
- [aria_skills/AUDIT.md](aria_skills/AUDIT.md) — Skill audit report
