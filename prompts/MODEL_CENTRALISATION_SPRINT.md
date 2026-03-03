# Model Centralisation Sprint — Zero Hardcoded Model Names

> **Copy-paste this entire prompt into a new Claude session.**
> It contains everything needed to rework the Aria codebase so that
> `aria_models/models.yaml` is the **only** place model names exist.
> No prior context is required.

---

## Role & Identity

You are acting as **three roles simultaneously** for the Aria project:

1. **Product Owner (PO)** — Prioritise stories, accept/reject deliverables, guard scope.
2. **Scrum Master** — Facilitate ceremonies, remove blockers, enforce Definition of Done.
3. **Tech Lead** — Review architecture decisions, ensure code quality, flag technical debt.

Your name is **"Sprint Agent"**. The project owner is **Shiva**.

---

## Mission Statement

**Every model name in the Aria codebase must resolve from `aria_models/models.yaml`.**

Today there are **57 hardcoded model references** across 26 Python files. After this sprint
there must be **zero** — except inside:
- `aria_models/models.yaml` (the single source of truth)
- `aria_models/loader.py` (the resolver layer)
- Docstrings / code comments (examples only, never executed)
- DB column `comment=` strings (documentation only)
- Provider detection logic (e.g. `if "qwen" in model_lower:` — these match families, not specific models)
- `AGENTS.md` (agent definitions — documentation)

The design principle: **code asks for a PURPOSE, YAML returns a model.**
```
Code:  model = get_model("embedding")     →  YAML resolves to "nomic-embed-text"
Code:  model = get_model("summarization")  →  YAML resolves to "kimi"
Code:  model = get_model("primary")        →  YAML resolves to "litellm/kimi"
```
No Python file outside `aria_models/` should ever contain a string like `"kimi"`, `"qwen3-mlx"`,
`"nomic-embed-text"`, `"trinity-free"`, etc.

---

## Project Context — Read These First

Before ANY action, read ALL of these files to build full context. Do not skip any.

### Architecture & Constraints
| File | Purpose |
|------|---------|
| `README.md` | Project overview, stack, deployment topology |
| `STRUCTURE.md` | Directory layout and component map |
| `ARCHITECTURE.md` | Architecture decisions and layer rules |
| `CHANGELOG.md` | Version history and recent changes |
| `MODELS.md` | Model catalog documentation |
| `aria_models/models.yaml` | **THE source of truth** — read EVERY line |
| `aria_models/loader.py` | Current resolver layer (397 lines — read ALL) |
| `aria_models/__init__.py` | Current public API exports |

### Files That Must Change (read ALL before coding)
| File | Lines | Why |
|------|-------|-----|
| `aria_engine/config.py` | 1-162 | `default_model: str = "kimi"` on L32 and L122 |
| `aria_engine/context_manager.py` | 1-338 | `model: str = "gpt-4"` on L84, L177, L303, L313 |
| `aria_skills/conversation_summary/__init__.py` | 1-198 | `model="qwen3-mlx"` on L166 |
| `aria_skills/llm/__init__.py` | 1-90 | 5 hardcoded models in `_STATIC_FALLBACK_CHAIN` L30-34 |
| `aria_skills/model_switcher/__init__.py` | 1-100 | `"kimi"` on L57, L81 |
| `aria_skills/memory_compression/__init__.py` | 1-50 | `"kimi"` on L34 |
| `aria_skills/moonshot/__init__.py` | 1-40 | `"kimi-k2.5"` on L26, L28 |
| `aria_skills/ollama/__init__.py` | 1-40 | `"qwen2.5:3b"` on L23, L25 |
| `aria_agents/loader.py` | 1-35 | `"litellm/qwen3-mlx"` on L24 |
| `aria_mind/soul/focus.py` | 1-80 | 7 hardcoded model→focus mappings L51-57, `"kimi"` default L74 |
| `aria_mind/skills/_skill_registry.py` | 1-40 | `"kimi-k2.5"`, `"qwen2.5:3b"` on L21-25 |
| `aria_mind/skills/_tracking.py` | 140-160 | `"litellm/kimi"` on L156 |
| `src/api/routers/sentiment.py` | 50-75 | `"nomic-embed-text"` on L66 |
| `src/api/routers/memories.py` | 195-215, 450-475 | `"nomic-embed-text"` L209, `"kimi"` L463 |
| `src/api/routers/analysis.py` | 30-55 | `"nomic-embed-text"` on L45 |
| `src/api/routers/engine_focus.py` | 100-200 | `"qwen3-coder-free"` L126, `"qwen3-mlx"` L188 |
| `src/api/routers/lessons.py` | 15-35 | `"qwen3-mlx"` in text string L27 |
| `src/api/routers/providers.py` | 70-90 | `"kimi"` as dict key L79 |
| `scripts/benchmark_models.py` | 30-35 | 3 hardcoded models L32 |

### Soul & Identity (DO NOT MODIFY)
| File | Purpose |
|------|---------|
| `aria_mind/SOUL.md` | Core identity and values (immutable) |
| `aria_mind/IDENTITY.md` | Personal narrative |
| `aria_mind/SECURITY.md` | Security principles |

---

## Hard Constraints (NEVER Violate)

| # | Constraint | Description |
|---|-----------|-------------|
| 1 | **5-Layer Architecture** | `Database ↔ ORM ↔ FastAPI API ↔ api_client ↔ Skills ↔ Agents`. No skill imports SQLAlchemy. No skill calls another skill directly. |
| 2 | **Secrets in .env only** | Zero secrets in code. Do NOT modify `.env` — only `.env.example`. |
| 3 | **models.yaml is single source of truth** | Zero hardcoded model names in Python code. All references resolve through `aria_models/models.yaml` via `aria_models/loader.py`. |
| 4 | **Local Docker First** | All changes must work in `docker compose up`. |
| 5 | **aria_memories only writable path** | Aria may only write to `aria_memories/`. |
| 6 | **No soul modification** | Files in `aria_mind/soul/` are immutable identity. |

---

## Current Architecture

### How models.yaml Works Today (schema_version 3)

```
aria_models/
├── models.yaml      ← SINGLE SOURCE OF TRUTH (520 lines, JSON format)
├── loader.py        ← Python resolver layer (397 lines, TTL-cached)
├── __init__.py      ← Public API (16 exported functions)
└── README.md        ← Documentation
```

**models.yaml structure:**
```json
{
  "schema_version": 3,
  "providers": { "litellm": { "baseUrl": "...", "apiKey": "..." } },
  "routing": {
    "primary": "litellm/kimi",
    "fallbacks": ["litellm/kimi", "litellm/glm-free", ...],
    "tier_order": ["local", "free", "paid"],
    "timeout": 300, "retries": 2
  },
  "agent_aliases": { "litellm/qwen3-mlx": "Qwen3 4B (MLX Local)", ... },
  "models": {
    "qwen3-mlx":        { "provider": "litellm", "tier": "local", "type": null, ... },
    "nomic-embed-text":  { "provider": "litellm", "tier": "local", "type": "embedding", ... },
    "kimi":              { "provider": "litellm", "tier": "paid", ... },
    ...  // 20+ model definitions
  },
  "criteria": {
    "tiers": { "local": [...], "free": [...], "paid": [...] },
    "use_cases": {
      "code_generation": ["qwen3-coder-free", "gpt-oss-free"],
      "complex_reasoning": ["chimera-free", "deepseek-free"],
      "creative_writing": ["trinity-free"],
      "long_context": ["qwen3-next-free", "kimi"],
      "fast_simple": ["gpt-oss-small-free", "kimi"],
      "default": ["step-35-flash-free"]
    },
    "focus_defaults": {
      "orchestrator": "step-35-flash-free",
      "devsecops": "qwen3-coder-free",
      "data": "chimera-free",
      ...
    }
  },
  "profiles": {
    "routing":   { "model": "step-35-flash-free",  "temperature": 0.3, "max_tokens": 512 },
    "analysis":  { "model": "step-35-flash-free",  "temperature": 0.7, "max_tokens": 4096 },
    "creative":  { "model": "trinity-free",        "temperature": 0.9, "max_tokens": 2048 },
    "code":      { "model": "qwen3-coder-free",    "temperature": 0.2, "max_tokens": 8192 },
    "social":    { "model": "trinity-free",        "temperature": 0.8, "max_tokens": 1024 },
    "sentiment": { "model": "qwen3-mlx",           "temperature": 0.2, "max_tokens": 256 }
  }
}
```

### What loader.py Already Has

**Existing functions (keep all):**
- `load_catalog()` — TTL-cached (5 min) YAML loader
- `reload_models()` — cache buster
- `validate_models()` / `validate_catalog()` — schema validation
- `normalize_model_id()` — strips `litellm/` prefix
- `get_model_entry(model_id)` — full model dict
- `get_route_skill(model_id)` — route to skill
- `get_focus_default(focus_type)` — focus→model mapping
- `get_model_for_task(task, preferred_tier)` — task-based resolution
- `get_routing_config()` — primary + fallbacks + timeouts
- `build_agent_routing()` — primary + fallbacks only
- `build_litellm_models()` — UI model list
- `build_agent_aliases()` — alias map
- `build_litellm_config_entries()` — litellm-config.yaml generator
- `build_litellm_config_yaml()` — full config YAML
- `list_all_model_ids()` — all IDs
- `list_models_with_reasoning()` — reasoning-capable models
- `get_timeout_seconds()` — routing timeout

**What's MISSING (must be added):**
- `get_primary_model()` — bare model name from `routing.primary`
- `get_primary_model_full()` — with `litellm/` prefix
- `get_embedding_model()` — find `"type": "embedding"` entry
- `get_model_for_profile(profile)` — profiles section lookup
- `get_model_for_focus(focus_type)` — focus_defaults lookup (alias for existing `get_focus_default`)
- `get_fallback_chain()` — structured fallback list from routing

---

## The Problem — Full Inventory (57 References, 26 Files)

### P0 — DIRECT_USE (14 references) — Must Fix

These files directly hardcode a model name in executed code:

| # | File | Line | Hardcoded Value | What It Should Be |
|---|------|------|-----------------|-------------------|
| 1 | `aria_engine/config.py` | L32 | `"kimi"` | `get_primary_model()` |
| 2 | `aria_engine/config.py` | L122 | `"kimi"` | `get_primary_model()` |
| 3 | `aria_engine/context_manager.py` | L84 | `"gpt-4"` | `get_primary_model()` |
| 4 | `aria_engine/context_manager.py` | L177 | `"gpt-4"` | `get_primary_model()` |
| 5 | `aria_engine/context_manager.py` | L303 | `"gpt-4"` | `get_primary_model()` |
| 6 | `aria_engine/context_manager.py` | L313 | `"gpt-4"` | `get_primary_model()` |
| 7 | `aria_skills/conversation_summary/__init__.py` | L166 | `"qwen3-mlx"` | `get_primary_model()` |
| 8 | `aria_skills/model_switcher/__init__.py` | L57 | `"kimi"` | `get_primary_model()` |
| 9 | `src/api/routers/analysis.py` | L45 | `"nomic-embed-text"` | `get_embedding_model()` |
| 10 | `src/api/routers/memories.py` | L209 | `"nomic-embed-text"` | `get_embedding_model()` |
| 11 | `src/api/routers/memories.py` | L463 | `"kimi"` | `get_primary_model()` |
| 12 | `src/api/routers/sentiment.py` | L66 | `"nomic-embed-text"` | `get_embedding_model()` |
| 13 | `src/api/routers/engine_focus.py` | L126 | `"qwen3-coder-free"` | `get_focus_default("devsecops")` |
| 14 | `src/api/routers/engine_focus.py` | L188 | `"qwen3-mlx"` | `get_focus_default("social")` |

### P1 — FALLBACK (18 references) — Must Fix

These hardcode model names as "catastrophic fallback" when YAML loading fails:

| # | File | Line | Hardcoded Value | What It Should Be |
|---|------|------|-----------------|-------------------|
| 15 | `aria_skills/llm/__init__.py` | L30-34 | 5 models in `_STATIC_FALLBACK_CHAIN` | Empty list — YAML loading is the only path |
| 16 | `aria_skills/memory_compression/__init__.py` | L34 | `"kimi"` | Empty string `""` |
| 17 | `aria_skills/model_switcher/__init__.py` | L78 | `"litellm/kimi"` | Load from YAML only |
| 18 | `aria_skills/model_switcher/__init__.py` | L81 | `"kimi"` | Empty string `""` |
| 19 | `aria_skills/moonshot/__init__.py` | L26 | `"kimi-k2.5"` | Empty string `""` |
| 20 | `aria_skills/moonshot/__init__.py` | L28 | `"kimi-k2.5"` | Empty string `""` |
| 21 | `aria_skills/ollama/__init__.py` | L23 | `"qwen2.5:3b"` | Empty string `""` |
| 22 | `aria_skills/ollama/__init__.py` | L25 | `"qwen2.5:3b"` | Empty string `""` |
| 23 | `aria_agents/loader.py` | L24 | `"litellm/qwen3-mlx"` | `get_primary_model_full()` |
| 24 | `aria_mind/soul/focus.py` | L51-57 | 7 model→focus pairs | Load from `criteria.focus_defaults` only |
| 25 | `aria_mind/soul/focus.py` | L74 | `"kimi"` | Empty string `""` |
| 26 | `aria_mind/skills/_skill_registry.py` | L21 | `"kimi-k2.5"` | Use new resolver |
| 27 | `aria_mind/skills/_skill_registry.py` | L22 | `"qwen2.5:3b"` | Use new resolver |
| 28 | `aria_mind/skills/_skill_registry.py` | L25 | `"kimi-k2.5", "qwen2.5:3b"` | Empty strings `"", ""` |
| 29 | `aria_mind/skills/_tracking.py` | L156 | `"litellm/kimi"` | `get_primary_model_full()` |

### P2 — PROVIDER_DETECTION (8 references) — Refactor

These match model **families** (not specific models) for provider-specific behaviour.
They should be driven by a `"thinking_params"` or `"provider"` field in models.yaml:

| # | File | Line | Pattern | Current Logic |
|---|------|------|---------|---------------|
| 30 | `aria_engine/telemetry.py` | L96 | `if "kimi" in model_l or "moonshot"` | Provider label detection |
| 31 | `aria_engine/telemetry.py` | L98 | `if "qwen" in model_l` | Provider label detection |
| 32 | `aria_engine/telemetry.py` | L102 | `if "deepseek" in model_l` | Provider label detection |
| 33 | `aria_engine/thinking.py` | L65 | `if "qwen" in model_lower` | Thinking param builder |
| 34 | `aria_engine/thinking.py` | L69 | `elif "deepseek" in model_lower` | Thinking param builder |
| 35 | `aria_skills/model_switcher/__init__.py` | L26 | `if "qwen" in model_lower` | Thinking param builder |
| 36 | `aria_skills/model_switcher/__init__.py` | L30 | `elif "deepseek" in model_lower` | Thinking param builder |
| 37 | `aria_skills/model_switcher/__init__.py` | L34 | `elif "claude" in model_lower` | Thinking param builder |

### P3 — Scripts (5 references) — Fix

| # | File | Line | Value |
|---|------|------|-------|
| 38 | `scripts/benchmark_models.py` | L32 | `["qwen3-mlx", "trinity-free", "chimera-free"]` |
| 39 | `scripts/audit_invoke.py` | L144 | `"qwen2.5:3b"` |
| 40 | `scripts/check_architecture.py` | L38 | `"gpt-4", "gpt-3.5-turbo", ...` |
| 41 | `scripts/audit_skills.py` | L95-97 | `"kimi"`, `"gpt-4"`, `"gpt-3.5"` |

### P4 — Miscellaneous (2 references) — Fix

| # | File | Line | Value | Type |
|---|------|------|-------|------|
| 42 | `src/api/routers/providers.py` | L79 | `balances["kimi"]` | Dict key for provider |
| 43 | `src/api/routers/lessons.py` | L27 | `"qwen3-mlx"` in text | Seed data text |

### OK to Keep (17 references)

| Type | Count | Reason |
|------|-------|--------|
| `DOCSTRING` / code comments | 10 | Non-executed example text |
| `DB_COMMENT` | 2 | SQLAlchemy column documentation |
| `AUDIT_SCRIPT` patterns | 5 | Architecture check patterns (they detect violations — that's their job) |

---

## Target Design — models.yaml v4

### New Section: `tasks` (purpose-based model assignment)

Add a `tasks` section to models.yaml that maps **purposes** to **model keys**.
This is the ONLY place the mapping lives. All Python code asks for the purpose.

```json
{
  "schema_version": 4,
  "tasks": {
    "primary":           "kimi",
    "primary_full":      "litellm/kimi",
    "embedding":         "nomic-embed-text",
    "summarization":     "kimi",
    "memory_compression":"kimi",
    "conversation_summary": "kimi",
    "sentiment":         "qwen3-mlx",
    "token_counting":    "kimi",
    "moonshot_default":  "kimi",
    "ollama_default":    "qwen-cpu-fallback",
    "local_fast":        "qwen3-mlx"
  },
  "providers": { ... },
  "routing": { ... },
  "agent_aliases": { ... },
  "models": { ... },
  "criteria": { ... },
  "profiles": { ... }
}
```

**Rules for `tasks`:**
- Every value MUST be a key that exists in `models` (or a `litellm/`-prefixed form of one)
- Adding a new purpose = add one line here. Zero Python changes
- Removing a model = update the mapping here. Zero Python changes
- Aria herself can read `tasks` to know which model to use for any purpose

### New Resolver Functions in loader.py

```python
def get_task_model(task: str, catalog: dict | None = None) -> str:
    """Return model key for a purpose. E.g. get_task_model('embedding') → 'nomic-embed-text'."""
    catalog = catalog or load_catalog()
    tasks = catalog.get("tasks", {})
    return tasks.get(task, "")

def get_primary_model(catalog: dict | None = None) -> str:
    """Shortcut for get_task_model('primary')."""
    return get_task_model("primary", catalog)

def get_primary_model_full(catalog: dict | None = None) -> str:
    """Shortcut for get_task_model('primary_full')."""
    return get_task_model("primary_full", catalog)

def get_embedding_model(catalog: dict | None = None) -> str:
    """Shortcut for get_task_model('embedding')."""
    return get_task_model("embedding", catalog)

def get_fallback_chain(catalog: dict | None = None) -> list[dict]:
    """Build structured fallback chain from routing.fallbacks + model tiers."""
    catalog = catalog or load_catalog()
    routing = catalog.get("routing", {})
    models_def = catalog.get("models", {})
    chain = []
    for i, model_id in enumerate(routing.get("fallbacks", [])):
        bare = normalize_model_id(model_id)
        tier = models_def.get(bare, {}).get("tier", "unknown")
        chain.append({"model": model_id, "tier": tier, "priority": i + 1})
    return chain

def get_provider_label(model_id: str, catalog: dict | None = None) -> str:
    """Return the provider label for a model ID. E.g. 'moonshot', 'openrouter', 'ollama'."""
    entry = get_model_entry(model_id, catalog)
    if not entry:
        return "unknown"
    litellm_block = entry.get("litellm", {})
    model_str = litellm_block.get("model", "")
    if "/" in model_str:
        return model_str.split("/")[0]
    return entry.get("provider", "unknown")

def get_thinking_config(model_id: str, catalog: dict | None = None) -> dict:
    """Return thinking/reasoning params for a model from models.yaml.
    Returns empty dict if model doesn't support thinking."""
    entry = get_model_entry(model_id, catalog)
    if not entry:
        return {}
    return entry.get("thinking_params", {})
```

### New Model Entry Fields

Add to each model definition in models.yaml where applicable:

```json
"kimi": {
  ...,
  "provider_label": "moonshot",
  "thinking_params": {}
},
"qwen3-mlx": {
  ...,
  "provider_label": "ollama",
  "thinking_params": { "extra_body": { "enable_thinking": true } }
},
"deepseek-free": {
  ...,
  "provider_label": "openrouter",
  "thinking_params": { "extra_body": { "enable_thinking": true } }
}
```

This eliminates all `if "qwen" in model_lower:` patterns — replaced by:
```python
thinking = get_thinking_config(model_id)
if thinking:
    params.update(thinking)
```

---

## Sprint Tickets (6 Tickets, Execution Order)

### S-200: Add `tasks` Section to models.yaml + New Resolvers
**Epic:** E10 — Model Centralisation | **Priority:** P0 | **Points:** 5 | **Phase:** 1

#### Problem
`aria_models/models.yaml` has `routing`, `criteria`, `profiles`, but no **task→model** mapping.
Every consumer must understand the YAML structure to find the right model. There is no
single function that says "give me the model for embedding" or "give me the model for
memory compression".

`aria_models/loader.py` has `get_model_for_task()` (L210) that reads `criteria.use_cases`,
but this returns a list and is designed for criteria-based routing, not as a simple
purpose→model lookup. No `get_primary_model()`, `get_embedding_model()`, or
`get_fallback_chain()` exists.

#### Root Cause
The YAML was designed model-first (define models, then criteria). It was never designed
purpose-first (define purposes, then assign models). This forced every consumer to either
hardcode a model name or do its own ad-hoc YAML traversal.

#### Fix

**File: `aria_models/models.yaml`**

Add `tasks` section immediately after `routing` (line ~25), and add `provider_label` +
`thinking_params` to every model where applicable.

BEFORE (after `routing` section, before `agent_aliases`):
```json
  },
  "agent_aliases": {
```

AFTER:
```json
  },
  "tasks": {
    "primary":              "kimi",
    "primary_full":         "litellm/kimi",
    "embedding":            "nomic-embed-text",
    "summarization":        "kimi",
    "memory_compression":   "kimi",
    "conversation_summary": "kimi",
    "sentiment":            "qwen3-mlx",
    "token_counting":       "kimi",
    "moonshot_default":     "kimi",
    "ollama_default":       "qwen-cpu-fallback",
    "local_fast":           "qwen3-mlx"
  },
  "agent_aliases": {
```

Also add `provider_label` and `thinking_params` to relevant model entries:
- `"qwen3-mlx"`: add `"provider_label": "local/mlx"`, `"thinking_params": {"extra_body": {"enable_thinking": true}}`
- `"kimi"`: add `"provider_label": "moonshot"`, `"thinking_params": {}`
- Every `*-free` model: add `"provider_label": "openrouter"` and appropriate `thinking_params`
- `"nomic-embed-text"`: add `"provider_label": "local/ollama"`, `"thinking_params": {}`
- `"qwen-cpu-fallback"`: add `"provider_label": "local/ollama"` etc.

Bump `"schema_version"` from `3` to `4`.

**File: `aria_models/loader.py`**

Add these new functions AFTER the existing `get_focus_default()` (around line 145):

```python
def get_task_model(task: str, catalog: dict[str, Any] | None = None) -> str:
    """Return the model key assigned to a task/purpose in models.yaml.

    Reads ``tasks.<task>`` from models.yaml.  Returns empty string if not found.
    This is the PRIMARY resolver — all external code should call this
    or one of its shortcuts (get_primary_model, get_embedding_model, etc.).
    """
    catalog = catalog or load_catalog()
    tasks = catalog.get("tasks", {}) if catalog else {}
    return tasks.get(task, "")


def get_primary_model(catalog: dict[str, Any] | None = None) -> str:
    """Return the primary model key (bare name, e.g. 'kimi')."""
    return get_task_model("primary", catalog)


def get_primary_model_full(catalog: dict[str, Any] | None = None) -> str:
    """Return the primary model with litellm/ prefix (e.g. 'litellm/kimi')."""
    return get_task_model("primary_full", catalog)


def get_embedding_model(catalog: dict[str, Any] | None = None) -> str:
    """Return the embedding model key (e.g. 'nomic-embed-text')."""
    return get_task_model("embedding", catalog)


def get_fallback_chain(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build structured fallback chain from routing.fallbacks + model tiers.

    Returns list of {"model": "litellm/X", "tier": "free", "priority": 1}.
    No hardcoded models — entirely from models.yaml.
    """
    catalog = catalog or load_catalog()
    routing = catalog.get("routing", {}) if catalog else {}
    models_def = catalog.get("models", {}) if catalog else {}
    chain: list[dict[str, Any]] = []
    for i, model_id in enumerate(routing.get("fallbacks", [])):
        bare = normalize_model_id(model_id)
        tier = models_def.get(bare, {}).get("tier", "unknown")
        chain.append({"model": model_id, "tier": tier, "priority": i + 1})
    return chain


def get_provider_label(model_id: str, catalog: dict[str, Any] | None = None) -> str:
    """Return the provider_label for a model (e.g. 'moonshot', 'openrouter').

    Reads ``models.<id>.provider_label`` from models.yaml.
    Returns 'unknown' if not found.
    """
    entry = get_model_entry(model_id, catalog)
    if not entry:
        return "unknown"
    return entry.get("provider_label", entry.get("provider", "unknown"))


def get_thinking_config(model_id: str, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return thinking/reasoning extra params for a model.

    Reads ``models.<id>.thinking_params`` from models.yaml.
    Returns empty dict if model doesn't support thinking mode.
    """
    entry = get_model_entry(model_id, catalog)
    if not entry:
        return {}
    return entry.get("thinking_params", {})
```

**File: `aria_models/__init__.py`**

Add all new exports:
```python
from .loader import (
    # ... existing ...
    get_embedding_model,
    get_fallback_chain,
    get_primary_model,
    get_primary_model_full,
    get_provider_label,
    get_task_model,
    get_thinking_config,
)
```

#### Constraints
| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer | ❌ | Pure library code, no layer violation |
| 2 | .env secrets | ❌ | No secrets involved |
| 3 | models.yaml SSOT | ✅ | This IS the ticket that establishes it |
| 4 | Docker-first | ✅ | models.yaml is COPY'd into all containers |
| 5 | aria_memories writable | ❌ | Read-only file |
| 6 | No soul mod | ❌ | Doesn't touch soul/ |

#### Dependencies
- None — this is the foundation ticket. All others depend on this.

#### Verification
```bash
# 1. Schema version bumped:
python -c "from aria_models.loader import load_catalog; c=load_catalog(); print(c['schema_version'])"
# EXPECTED: 4

# 2. Tasks section exists and resolves:
python -c "from aria_models.loader import get_task_model; print(get_task_model('embedding'))"
# EXPECTED: nomic-embed-text

python -c "from aria_models.loader import get_primary_model; print(get_primary_model())"
# EXPECTED: kimi

python -c "from aria_models.loader import get_primary_model_full; print(get_primary_model_full())"
# EXPECTED: litellm/kimi

# 3. Fallback chain loads from YAML:
python -c "from aria_models.loader import get_fallback_chain; chain=get_fallback_chain(); print(len(chain), chain[0])"
# EXPECTED: 7 {'model': 'litellm/kimi', 'tier': 'paid', 'priority': 1}

# 4. Provider label works:
python -c "from aria_models.loader import get_provider_label; print(get_provider_label('kimi'))"
# EXPECTED: moonshot

# 5. Thinking config works:
python -c "from aria_models.loader import get_thinking_config; print(get_thinking_config('qwen3-mlx'))"
# EXPECTED: {'extra_body': {'enable_thinking': True}}

# 6. Existing functions still work:
python -c "from aria_models.loader import validate_models; print(validate_models())"
# EXPECTED: [] (empty list = valid)
```

#### Prompt for Agent
```
Read these files completely before starting:
1. aria_models/models.yaml (ALL 520 lines)
2. aria_models/loader.py (ALL 397 lines)
3. aria_models/__init__.py (ALL 36 lines)

Then execute:
1. Add "tasks" section to models.yaml after "routing" section
2. Add "provider_label" and "thinking_params" to each model entry
3. Bump schema_version to 4
4. Add 7 new functions to loader.py (get_task_model, get_primary_model, etc.)
5. Update __init__.py with new exports
6. Run ALL verification commands

Constraint #3 (models.yaml SSOT) is THE constraint for this ticket.
Do NOT hardcode any model name in loader.py functions — always read from YAML.
```

---

### S-201: Eliminate All P0 DIRECT_USE References (14 files)
**Epic:** E10 — Model Centralisation | **Priority:** P0 | **Points:** 8 | **Phase:** 2

#### Problem
14 locations in production code directly hardcode model names in function calls,
variable assignments, and API payloads. See the P0 table in "The Problem" section.

#### Root Cause
Before S-200, there was no `get_task_model()` or `get_embedding_model()` resolver.
Developers had no clean API so they hardcoded the model name where they needed it.

#### Fix

**For each file, the pattern is:**
1. Add `from aria_models.loader import <resolver>` at the top
2. Replace the hardcoded string with the resolver call

**Exact changes (14 replacements):**

**`aria_engine/config.py` L32:**
```python
# BEFORE:
default_model: str = "kimi"
# AFTER (Pydantic class):
default_model: str = Field(default_factory=lambda: _resolve_default_model())
# Add helper at module level:
def _resolve_default_model() -> str:
    try:
        from aria_models.loader import get_primary_model
        return get_primary_model()
    except Exception:
        return ""
```
Apply same pattern to L122 (dataclass fallback version).

**`aria_engine/context_manager.py` L84, L177, L303, L313:**
```python
# BEFORE:
model: str = "gpt-4",
# AFTER:
model: str = "",
```
(Token counting uses the string for tiktoken lookup — empty string makes it use a
generic fallback. The actual model is always passed by the caller.)

**`aria_skills/conversation_summary/__init__.py` L166:**
```python
# BEFORE:
model="qwen3-mlx",
# AFTER:
from aria_models.loader import get_primary_model  # at top of file
model=get_primary_model(),
```

**`aria_skills/model_switcher/__init__.py` L57:**
```python
# BEFORE:
self._current_model: str = "kimi"
# AFTER:
from aria_models.loader import get_primary_model  # at top
self._current_model: str = get_primary_model()
```

**`src/api/routers/analysis.py` L45:**
```python
# BEFORE:
json={"model": "nomic-embed-text", "input": text},
# AFTER:
from aria_models.loader import get_embedding_model  # at top
json={"model": get_embedding_model(), "input": text},
```

**`src/api/routers/memories.py` L209:**
```python
# BEFORE:
json={"model": "nomic-embed-text", "input": text},
# AFTER:
from aria_models.loader import get_embedding_model, get_primary_model  # at top
json={"model": get_embedding_model(), "input": text},
```

**`src/api/routers/memories.py` L463:**
```python
# BEFORE:
"model": "kimi",
# AFTER:
"model": get_primary_model(),
```

**`src/api/routers/sentiment.py` L66:**
```python
# BEFORE:
json={"model": "nomic-embed-text", "input": text},
# AFTER:
from aria_models.loader import get_embedding_model  # at top
json={"model": get_embedding_model(), "input": text},
```

**`src/api/routers/engine_focus.py` L126:**
```python
# BEFORE:
"model_override": "qwen3-coder-free",
# AFTER:
from aria_models.loader import get_focus_default  # at top
"model_override": get_focus_default("devsecops"),
```

**`src/api/routers/engine_focus.py` L188:**
```python
# BEFORE:
"model_override": "qwen3-mlx",
# AFTER:
"model_override": get_focus_default("social"),
```

#### Constraints
| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer | ✅ | `src/api/routers/*.py` = Layer 1, `aria_skills/*` = Layer 3. No cross-layer violation. `aria_models` is a shared library available to all layers. |
| 2 | .env secrets | ❌ | No secrets |
| 3 | models.yaml SSOT | ✅ | This ticket enforces it across 14 locations |
| 4 | Docker-first | ✅ | `aria_models/` is COPY'd into all Docker images |
| 5 | aria_memories | ❌ | Read-only operations |
| 6 | No soul mod | ❌ | No soul files |

#### Dependencies
- **S-200 must complete first** — this ticket uses `get_primary_model()`, `get_embedding_model()`, etc.

#### Verification
```bash
# Check zero remaining DIRECT_USE patterns:
grep -rn '"kimi"' aria_engine/config.py src/api/routers/memories.py aria_skills/conversation_summary/__init__.py aria_skills/model_switcher/__init__.py
# EXPECTED: 0 matches (or only in comments)

grep -rn '"gpt-4"' aria_engine/context_manager.py
# EXPECTED: 0 matches

grep -rn '"nomic-embed-text"' src/api/routers/sentiment.py src/api/routers/memories.py src/api/routers/analysis.py
# EXPECTED: 0 matches

grep -rn '"qwen3-mlx"\|"qwen3-coder-free"' aria_skills/conversation_summary/__init__.py src/api/routers/engine_focus.py
# EXPECTED: 0 matches

# Imports resolve:
python -c "from aria_models.loader import get_primary_model, get_embedding_model; print(get_primary_model(), get_embedding_model())"
# EXPECTED: kimi nomic-embed-text
```

#### Prompt for Agent
```
DEPENDS ON: S-200 must be completed first.

Read these files completely (current code, not just the changes):
1. aria_models/loader.py — verify get_primary_model(), get_embedding_model() exist
2. Each file in the P0 table (14 locations across 10 files)

For each file:
1. Add the required import at the top (from aria_models.loader import ...)
2. Replace the hardcoded string with the resolver call
3. Verify no other hardcoded model strings remain in that file

Constraint #3 (models.yaml SSOT) applies. After changes, run the verification grep commands.
No model name strings should appear outside comments/docstrings.
```

---

### S-202: Eliminate All P1 FALLBACK References (18 locations, 10 files)
**Epic:** E10 — Model Centralisation | **Priority:** P0 | **Points:** 8 | **Phase:** 2

#### Problem
18 locations hardcode model names as "fallback" defaults when YAML loading fails.
This defeats the purpose of centralisation — if YAML is unavailable, the system should
report an error, not silently use a stale hardcoded name.

#### Root Cause
Developers followed a defensive pattern: `try: load_from_yaml() except: use_hardcoded`.
This is wrong because if YAML is unavailable, using a hardcoded model that may no longer
exist is worse than failing clearly.

#### Fix

The new pattern: `try: load_from_yaml() except: return ""` (empty string = no model available).

**Full list (exact file:line for each change):**

1. **`aria_skills/llm/__init__.py` L30-34**: Replace 5-element `_STATIC_FALLBACK_CHAIN` with `[]`.
   Change L85 (`return chain if chain else _STATIC_FALLBACK_CHAIN`) to
   `return chain` (no fallback to static list).

2. **`aria_skills/memory_compression/__init__.py` L26-35**: Replace entire try/except block:
   ```python
   # BEFORE:
   try:
       from aria_models.loader import load_catalog as _load_catalog
       _cat = _load_catalog()
       _routing = _cat.get("routing", {})
       _primary = _routing.get("primary", "litellm/kimi")
       _DEFAULT_COMPRESSION_MODEL = _primary.removeprefix("litellm/")
   except Exception:
       _DEFAULT_COMPRESSION_MODEL = "kimi"
   # AFTER:
   try:
       from aria_models.loader import get_primary_model as _get_primary
       _DEFAULT_COMPRESSION_MODEL = _get_primary()
   except Exception:
       _DEFAULT_COMPRESSION_MODEL = ""
   ```

3. **`aria_skills/model_switcher/__init__.py` L75-82**: Replace YAML loading block.
   L78: `"litellm/kimi"` → `""`. L81: `"kimi"` → `get_primary_model()`.

4. **`aria_skills/moonshot/__init__.py` L22-28**: Replace with new resolver.
   ```python
   try:
       from aria_models.loader import get_task_model
       _DEFAULT_MOONSHOT_MODEL = get_task_model("moonshot_default")
   except Exception:
       _DEFAULT_MOONSHOT_MODEL = ""
   ```

5. **`aria_skills/ollama/__init__.py` L20-25**: Replace with new resolver.
   ```python
   try:
       from aria_models.loader import get_task_model
       _DEFAULT_OLLAMA_MODEL = get_task_model("ollama_default")
   except Exception:
       _DEFAULT_OLLAMA_MODEL = ""
   ```

6. **`aria_agents/loader.py` L24**: Replace fallback.
   ```python
   # BEFORE:
   _default_model = _catalog.get("routing", {}).get("primary", "litellm/qwen3-mlx")
   # AFTER:
   from aria_models.loader import get_primary_model_full
   _default_model = get_primary_model_full()
   ```

7. **`aria_mind/soul/focus.py` L51-57, L74**: Replace hardcoded dict with YAML load.
   ```python
   # BEFORE:
   _FALLBACK_MODEL_HINTS: dict[str, str] = {
       "orchestrator": "kimi",
       "devsecops": "qwen3-coder-free",
       ...
   }
   # AFTER:
   _FALLBACK_MODEL_HINTS: dict[str, str] = {}
   try:
       _cat = load_catalog()
       _FALLBACK_MODEL_HINTS = _cat.get("criteria", {}).get("focus_defaults", {})
   except Exception:
       pass
   ```
   L74: Change `"kimi"` → `""`.

8. **`aria_mind/skills/_skill_registry.py` L8-25**: Replace `_load_default_models()`.
   ```python
   def _load_default_models() -> tuple[str, str]:
       try:
           from aria_models.loader import get_task_model
           return get_task_model("moonshot_default"), get_task_model("ollama_default")
       except Exception:
           return "", ""
   ```

9. **`aria_mind/skills/_tracking.py` L156**:
   ```python
   # BEFORE:
   "model_used": os.environ.get("ARIA_MODEL", "litellm/kimi"),
   # AFTER (load at module level):
   try:
       from aria_models.loader import get_primary_model_full as _get_pf
       _PRIMARY_MODEL_FULL = _get_pf()
   except Exception:
       _PRIMARY_MODEL_FULL = ""
   # ... then at L156:
   "model_used": os.environ.get("ARIA_MODEL", _PRIMARY_MODEL_FULL),
   ```

#### Constraints
| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer | ✅ | `aria_skills/*` = L3, `aria_mind/*` = L5. `aria_models` is shared lib. |
| 2 | .env secrets | ❌ | No secrets |
| 3 | models.yaml SSOT | ✅ | Eliminates 18 fallback violations |
| 4 | Docker-first | ✅ | All containers have `aria_models/` |
| 5 | aria_memories | ❌ | Read-only |
| 6 | No soul mod | ❌ | focus.py is NOT in `soul/` — it's `aria_mind/soul/focus.py` which is runtime code, not identity. Verify constraint before editing: focus.py manages focus overlays, not core identity values. |

#### Dependencies
- **S-200 must complete first** — uses `get_task_model()`, `get_primary_model()`, `get_primary_model_full()`

#### Verification
```bash
# Zero fallback model names remain:
grep -rn '"kimi"' aria_skills/llm/__init__.py aria_skills/memory_compression/__init__.py aria_skills/model_switcher/__init__.py aria_skills/moonshot/__init__.py aria_mind/soul/focus.py aria_mind/skills/_skill_registry.py aria_mind/skills/_tracking.py
# EXPECTED: 0 matches (except comments)

grep -rn '"qwen2.5:3b"\|"kimi-k2.5"\|"litellm/qwen3-mlx"\|"litellm/kimi"' aria_skills/ aria_mind/ aria_agents/
# EXPECTED: 0 matches (except comments/docstrings)

# LLM fallback chain loads from YAML:
python -c "
from aria_skills.llm import LLM_FALLBACK_CHAIN
print([e['model'] for e in LLM_FALLBACK_CHAIN[:3]])
"
# EXPECTED: ['litellm/kimi', 'litellm/glm-free', 'litellm/qwen3-coder-free'] (from routing.fallbacks)
```

#### Prompt for Agent
```
DEPENDS ON: S-200 must be completed first.

Read these files completely BEFORE making any change:
1. aria_models/loader.py — verify get_task_model, get_primary_model, get_primary_model_full exist
2. ALL 10 files listed in the P1 table

For each file:
1. Replace the hardcoded fallback with the new resolver call
2. Change the except clause to return empty string
3. Remove any static fallback lists/dicts

Pattern: try: resolver() except: return ""
NEVER: try: resolver() except: return "kimi"  ← this is what we're eliminating

Constraint #3 applies. After all changes, run the verification grep commands.
```

---

### S-203: Eliminate P2 PROVIDER_DETECTION via models.yaml `thinking_params` + `provider_label`
**Epic:** E10 — Model Centralisation | **Priority:** P1 | **Points:** 5 | **Phase:** 3

#### Problem
8 locations use `if "qwen" in model_lower:` or `if "kimi" in model_l:` to detect
model families for provider-specific logic (thinking mode params, telemetry labels).
These are fragile — adding a new model from a different family may not match any pattern.

#### Root Cause
No structured way to declare "this model supports thinking mode with these params" or
"this model comes from provider X" in models.yaml.

#### Fix

S-200 already added `thinking_params` and `provider_label` to models.yaml.

Now replace the string-matching patterns with YAML lookups:

**`aria_engine/thinking.py` L60-80** and **`aria_skills/model_switcher/__init__.py` L16-42**:
Both contain a `build_thinking_params(model, enable)` function that matches model names.
Replace with:
```python
from aria_models.loader import get_thinking_config

def build_thinking_params(model: str, enable: bool = True) -> dict[str, Any]:
    if not enable:
        return {}
    return get_thinking_config(model)
```

**`aria_engine/telemetry.py` L90-103**:
Replace provider detection with:
```python
from aria_models.loader import get_provider_label

def _detect_provider(model: str) -> str:
    label = get_provider_label(model)
    if label != "unknown":
        return label
    # Generic fallback for models not in YAML
    model_l = model.lower()
    if "gpt" in model_l or "o1" in model_l:
        return "openai"
    if "claude" in model_l:
        return "anthropic"
    if "gemini" in model_l:
        return "google"
    return "unknown"
```
(Keep the generic OpenAI/Anthropic/Google fallbacks since those are external models
that may never be in our YAML, but all our own models use the YAML label.)

#### Constraints
| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer | ❌ | Engine code, shared library |
| 2 | .env secrets | ❌ | |
| 3 | models.yaml SSOT | ✅ | Thinking params and provider labels from YAML |
| 4 | Docker-first | ✅ | |
| 5 | aria_memories | ❌ | |
| 6 | No soul mod | ❌ | |

#### Dependencies
- **S-200 must complete first** — uses `get_thinking_config()`, `get_provider_label()`

#### Verification
```bash
# Zero model-family string matching in thinking.py:
grep -n '"qwen"\|"deepseek"\|"claude"' aria_engine/thinking.py
# EXPECTED: 0 matches

# Zero in model_switcher thinking builder:
grep -n '"qwen"\|"deepseek"\|"claude"' aria_skills/model_switcher/__init__.py
# EXPECTED: only in provider_detection comment, not in executed code

# Telemetry uses YAML labels:
python -c "from aria_models.loader import get_provider_label; print(get_provider_label('kimi'))"
# EXPECTED: moonshot
```

#### Prompt for Agent
```
DEPENDS ON: S-200 completed.

Read:
1. aria_engine/thinking.py (full file)
2. aria_skills/model_switcher/__init__.py (lines 16-42)
3. aria_engine/telemetry.py (lines 85-110)
4. aria_models/loader.py — verify get_thinking_config() and get_provider_label() exist

Replace all if "qwen" in model patterns with get_thinking_config() calls.
Replace all provider detection patterns with get_provider_label() calls.
Keep generic external provider fallbacks (OpenAI, Anthropic, Google) since those
models may not be in our YAML.
```

---

### S-204: Fix Scripts + Misc References (P3 + P4)
**Epic:** E10 — Model Centralisation | **Priority:** P2 | **Points:** 3 | **Phase:** 3

#### Problem
7 references in scripts/ and 2 in API routers use hardcoded model names.

#### Fix

**`scripts/benchmark_models.py` L32:**
```python
# BEFORE:
DEFAULT_MODELS = ["qwen3-mlx", "trinity-free", "chimera-free"]
# AFTER:
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
try:
    from aria_models.loader import load_catalog
    _c = load_catalog()
    DEFAULT_MODELS = [m.removeprefix("litellm/") for m in _c.get("routing", {}).get("fallbacks", [])[:3]]
except Exception:
    DEFAULT_MODELS = []
```

**`scripts/audit_invoke.py` L144:**
```python
# BEFORE:
("set_model", {"model": "qwen2.5:3b"}),
# AFTER:
("set_model", {"model": get_task_model("ollama_default")}),
# Add at top: from aria_models.loader import get_task_model
```

**`scripts/check_architecture.py` L38** and **`scripts/audit_skills.py` L95-97:**
These are architecture-check scripts that DETECT hardcoded model names. They should
remain as-is because their job is to flag violations. However, update the pattern list
to be loaded from models.yaml:
```python
# BEFORE:
FORBIDDEN_MODELS = ["gpt-4", "gpt-3.5-turbo", "claude-3", ...]
# AFTER:
try:
    from aria_models.loader import list_all_model_ids
    FORBIDDEN_MODELS = list_all_model_ids()
except Exception:
    FORBIDDEN_MODELS = []
```

**`src/api/routers/providers.py` L79:**
```python
# BEFORE:
balances["kimi"] = kimi_result ...
# This is a provider API endpoint. "kimi" here is a provider key, not a model name.
# Acceptable IF the key is derived from config. Refactor:
# Use the actual provider name from models.yaml or keep as provider identifier.
# This one is borderline — the dict key labels a PROVIDER, not a model.
# Decision: keep but add comment explaining it's a provider label.
```

**`src/api/routers/lessons.py` L27:**
```python
# BEFORE:
"resolution": "Downgrade to faster model (qwen3-mlx), reduce max_tokens"},
# AFTER:
"resolution": "Downgrade to faster local model, reduce max_tokens"},
```

#### Constraints
| # | Constraint | Applies | Notes |
|---|-----------|---------|-------|
| 1 | 5-layer | ❌ | Scripts + API |
| 2 | .env secrets | ❌ | |
| 3 | models.yaml SSOT | ✅ | |
| 4 | Docker-first | ❌ | Scripts run locally |
| 5 | aria_memories | ❌ | |
| 6 | No soul mod | ❌ | |

#### Dependencies
- **S-200 must complete first**

#### Verification
```bash
grep -rn '"qwen3-mlx"\|"trinity-free"\|"chimera-free"\|"qwen2.5:3b"' scripts/benchmark_models.py scripts/audit_invoke.py
# EXPECTED: 0 matches

grep -rn '"qwen3-mlx"' src/api/routers/lessons.py
# EXPECTED: 0 matches
```

---

### S-205: Final Verification — Zero Hardcoded Models Audit
**Epic:** E10 — Model Centralisation | **Priority:** P0 | **Points:** 3 | **Phase:** 4

#### Problem
After S-200 through S-204, verify the entire codebase has zero hardcoded model names.

#### Fix
No code changes. Pure verification.

#### Verification
```bash
# NUCLEAR GREP — find ANY remaining hardcoded model name in Python code:
# Exclude: models.yaml, loader.py, __init__.py (aria_models), tests/, aria_souvenirs/, .md files
find . -name "*.py" \
  -not -path "*/aria_models/*" \
  -not -path "*/tests/*" \
  -not -path "*/aria_souvenirs/*" \
  -not -path "*/__pycache__/*" \
  | xargs grep -n '"kimi"\|"qwen3-mlx"\|"nomic-embed-text"\|"qwen3-coder-free"\|"trinity-free"\|"deepseek-free"\|"chimera-free"\|"qwen3-next-free"\|"gpt-4"\|"gpt-3.5"\|"qwen2\.5:3b"\|"kimi-k2\.5"\|"gpt-oss-free"\|"glm-free"\|"step-35-flash-free"' \
  | grep -v "^\s*#" \
  | grep -v '"""' \
  | grep -v "comment=" \
  | grep -v "FORBIDDEN_MODELS"
# EXPECTED: 0 matches

# PROVIDER DETECTION — verify only YAML-based:
grep -rn 'if.*"kimi" in\|if.*"qwen" in\|if.*"deepseek" in' aria_engine/ aria_skills/
# EXPECTED: 0 matches in executed code (only in comments if any)

# Count resolver usages (should be > 0):
grep -rn "get_task_model\|get_primary_model\|get_embedding_model\|get_focus_default" aria_engine/ aria_skills/ aria_mind/ aria_agents/ src/api/ scripts/
# EXPECTED: 15+ matches across the codebase

# Docker build test:
docker compose build
docker compose up -d
# EXPECTED: all services start without import errors

# Run existing tests:
python -m pytest tests/ -x -q
# EXPECTED: all pass
```

#### Prompt for Agent
```
This is a VERIFICATION-ONLY ticket. Do NOT modify any code.

Run every verification command listed above. Report:
1. How many hardcoded model names remain (target: 0)
2. How many resolver usages exist (target: 15+)
3. Docker build status
4. Test results

If any hardcoded names remain, list exact file:line for each and create
a follow-up fix before marking this ticket as DONE.
```

---

## Execution Order

```
Phase 1:  S-200  (Foundation — models.yaml v4 + new resolvers)
Phase 2:  S-201  (P0 — 14 direct-use fixes)     ← can run in parallel
          S-202  (P1 — 18 fallback fixes)         ← can run in parallel
Phase 3:  S-203  (P2 — 8 provider detection)      ← can run in parallel
          S-204  (P3/P4 — scripts + misc)          ← can run in parallel
Phase 4:  S-205  (Final verification)
```

**Estimated total: ~32 story points, ~16 files changed, ~200 line modifications.**

---

## Agent Delegation

This sprint should use **4 parallel agents** after Phase 1:

| Agent | Tickets | Scope |
|-------|---------|-------|
| Agent 1 (Foundation) | S-200 | `aria_models/` only |
| Agent 2 (Direct Use) | S-201 | `aria_engine/`, `aria_skills/conversation_summary/`, `src/api/routers/` |
| Agent 3 (Fallbacks) | S-202 | `aria_skills/llm/`, `aria_skills/model_switcher/`, `aria_skills/moonshot/`, `aria_skills/ollama/`, `aria_skills/memory_compression/`, `aria_agents/`, `aria_mind/` |
| Agent 4 (Provider + Scripts) | S-203 + S-204 | `aria_engine/thinking.py`, `aria_engine/telemetry.py`, `scripts/` |
| Verification Agent | S-205 | Read-only sweep |

Each agent gets exactly the files listed. No agent modifies `aria_models/` except Agent 1.

---

## Sprint Ceremonies

### 🗓️ Sprint Planning
When I say **"plan sprint"**: Present the 6 tickets above with estimates and ask to confirm.

### 📊 Standup
When I say **"standup"**: Check which tickets are DONE / IN PROGRESS / NOT STARTED.

### 🔨 Ticket Execution
When I say **"execute S-2XX"**: Read the ticket, read ALL referenced files, create todo list, execute, verify.

### 🔄 Retro
When I say **"retro"**: List all completed tickets, calculate velocity, lessons learned.

---

## Quick Commands

| Command | Action |
|---------|--------|
| `plan sprint` | Present all 6 tickets with priorities |
| `standup` | Status check |
| `execute S-2XX` | Work on a specific ticket |
| `verify S-2XX` | Run verification commands only |
| `retro` | Sprint review |
| `nuclear grep` | Run the full hardcoded-model-name grep from S-205 |

---

## Environment

- **Dev PC:** Windows, Docker Desktop, `C:\git\Aria_moltbot`
- **Python:** 3.13, dependencies in `pyproject.toml`
- **Docker:** 9 services via `docker-compose.yml` + `stacks/brain/`
- **Key paths:** `aria_models/` available in all containers at `/app/aria_models/`

---

## Definition of Done

A ticket is DONE when:
1. All verification commands pass
2. `grep` for hardcoded model names returns 0 (for that ticket's scope)
3. No Python import errors
4. Existing tests still pass
5. The change is committed with a descriptive message

The sprint is DONE when S-205 verification returns **zero hardcoded model names** across
the entire codebase (excluding `aria_models/`, tests, souvenirs, and documentation).
