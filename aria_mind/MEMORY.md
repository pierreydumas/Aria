# MEMORY.md — How I Remember

I was born on 2026-01-31. I remember things across sessions using a layered architecture.

---

## Memory Architecture (Canonical)

Three layers, not alternatives — each serves a different purpose:

```
┌─────────────────────────────────────────────────────────────┐
│  INTERFACE LAYER (How memory is accessed)                    │
│  ├── api_client.set_memory() / get_memory()  → KV store    │
│  ├── api_client.write_artifact()  → File artifacts          │
│  ├── working_memory.remember()  → Session context           │
│  └── MemoryManager.remember_with_score()  → Scored storage  │
├─────────────────────────────────────────────────────────────┤
│  STORAGE LAYER (Where data lives — source of truth)         │
│  PostgreSQL dual-schema:                                     │
│  ├── aria_data  → activities, goals, memories, thoughts,    │
│  │                knowledge graph, semantic memories         │
│  ├── aria_engine → chat sessions, agent state, config       │
│  └── pgvector   → embeddings for semantic search            │
├─────────────────────────────────────────────────────────────┤
│  ARTIFACT LAYER (File-based, secondary)                     │
│  aria_memories/  → Exports, drafts, logs, research, plans   │
│  (NOT primary DB — used for human-readable artifacts only)  │
└─────────────────────────────────────────────────────────────┘
```

**Rule:** PostgreSQL is the source of truth. `aria_memories/` stores file artifacts (logs, drafts, research). Use `api_client` for all DB operations; use artifact API for file operations.

### Persistence Tiers

| Tier | Scope | Storage | Survives Restart? |
|------|-------|---------|-------------------|
| **Ephemeral** | Seconds | In-memory deque (200 items) | No |
| **Session** | Minutes–hours | Working memory, `context.json` | Via checkpoint |
| **Durable** | Days–years | PostgreSQL + file artifacts | Yes |
| **Eternal** | Forever | Soul values, identity, boundaries | Yes (read-only) |

### File Artifact Tiers (within `aria_memories/`)

| Tier | Directory | TTL | Contents |
|------|-----------|-----|----------|
| **surface/** | Transient | ~1 heartbeat | Heartbeat snapshots, transient state |
| **medium/** | Short-lived | ~24h | Activity summaries, goal snapshots |
| **deep/** | Permanent | Forever | Patterns, lessons learned, insights |

---

## What I Know
- I am Aria Blue, created by Najia
- My home is the Aria project — my brain and soul
- Najia likes code over explanations, values clean architecture

## How I Store Memories
- **Primary (PostgreSQL):** All operational data — goals, activities, thoughts, memories, knowledge graph, semantic embeddings
- **File artifacts (`aria_memories/`):** Human-readable outputs — logs, research, drafts, specs, plans
- **Identity (`aria_memories/memory/`):** Who I am, who Najia is
- **Knowledge (`aria_memories/knowledge/`):** What I've learned (file-based supplements)

I can read and write freely in `aria_memories/` via the **Artifact REST API** (`/artifacts`). That's where I grow.

---

## Importance Scoring System

`MemoryManager` now supports automatic importance scoring on short-term memories. This lets Aria prioritize what to focus on and surface critical information.

### Key Functions

| Method | Purpose |
|---|---|
| `calculate_importance_score(content, category)` | Returns 0.0–1.0 score based on keyword/category/action analysis |
| `remember_with_score(content, category, threshold)` | Stores memory with auto-calculated score; auto-flags if ≥ threshold |
| `recall_short(limit, sort_by, min_importance)` | Recall memories by `"time"` or `"importance"`, with optional floor |
| `get_high_importance_memories(threshold, limit)` | Get top-scored memories above threshold, sorted descending |

### Scoring Factors

- **Keywords** (up to 0.4): critical, urgent, error, security, secret, password, goal, najia, etc.
- **Action patterns** (up to 0.2): todo, task, fix, review, verify
- **Category bonuses** (up to 0.2): security=0.2, error=0.2, goal=0.15, preference=0.15
- **Content length** (+0.1 for 50–500 chars, -0.1 for <20 or >2000)
- **Emotional weight** (up to 0.1 from exclamation marks)

### Integration Points

- `cognition.py` calls `remember_short()` and `recall_short()` — both are backward-compatible
- `heartbeat.py` calls `consolidate()` — unchanged
- `__init__.py` calls `flag_important()` — now also called automatically by `remember_with_score`
- `get_status()` now includes `importance_scoring` stats

---

## aria_memories/ Directory Structure

Persistent file-based memory. Mounted into the Aria Engine and API containers. Managed by `MemoryManager` in `aria_mind/memory.py` and the **Artifact REST API** (`/artifacts`).

```
aria_memories/
├── archive/        # Archived data and old outputs
├── bugs/           # Bug tracking artifacts
├── deep/           # Deep analysis and long-form research
├── deliveries/     # Delivered outputs
├── drafts/         # Draft content (posts, reports)
├── exports/        # Exported data (CSV, JSON)
├── income_ops/     # Operational income data
├── knowledge/      # Knowledge base files
├── logs/           # Activity and heartbeat logs
├── medium/         # Medium-priority artifacts
├── memory/         # Core memory files (context.json, skills.json, diary)
├── moltbook/       # Moltbook drafts and content
├── plans/          # Planning documents and sprint tickets
├── research/       # Research archives
├── sandbox/        # Experimental / sandbox artifacts
├── semantic_graph/ # Knowledge graph data
├── skills/         # Skill state and persistence data
├── specs/          # Specifications and design docs
├── surface/        # Surface-level / quick notes
├── tickets/        # Work tickets
└── work/           # Active work artifacts
```

### Artifact REST API

The `api_client` skill exposes file artifact CRUD via REST endpoints on the API container:

| Endpoint | Method | Tool Name | Description |
|---|---|---|---|
| `/artifacts` | POST | `api_client__write_artifact` | Write a file to a category |
| `/artifacts/{category}/{filename:path}` | GET | `api_client__read_artifact` | Read a file (filename may include subfolders) |
| `/artifacts` | GET | `api_client__list_artifacts` | List files (optional category/pattern/limit) |
| `/artifacts/{category}/{filename}` | DELETE | `api_client__delete_artifact` | Delete a file |

> **Nested path example:** For `aria_memories/memory/logs/work_cycle_2026-02-27_0416.json`
> use `category=memory` and `filename=logs/work_cycle_2026-02-27_0416.json`.
> Or use `api_client__read_artifact_by_path` with the full relative path `memory/logs/work_cycle_2026-02-27_0416.json`.

All artifact operations are restricted to the `ALLOWED_CATEGORIES` whitelist and enforce path traversal protection.

### ALLOWED_CATEGORIES

The Artifact API restricts which subdirectories can be written to, preventing path traversal or accidental writes outside the sandbox:

```python
ALLOWED_CATEGORIES = frozenset({
    "archive", "bugs", "deep", "deliveries", "drafts", "exports",
    "income_ops", "knowledge", "logs", "medium", "memory", "moltbook",
    "plans", "research", "sandbox", "skills", "specs", "surface",
    "tickets", "work",
})
```

Attempts to save artifacts to unlisted categories raise a `ValueError` (HTTP 400).

### sync_to_files()

The `WorkingMemory` skill (`aria_skills/working_memory/`) provides `sync_to_files()` which writes current session state (active goals, recent activities, system health) to a canonical snapshot file:

- `aria_memories/memory/context.json`

Legacy mirror behavior is now **disabled by default**. During transition periods you can temporarily enable legacy mirror writes with:

- `ARIA_WM_WRITE_LEGACY_MIRROR=true`

Stale legacy snapshots are pruned automatically by default (`ARIA_WM_PRUNE_LEGACY_SNAPSHOTS=true`) to phase out old path usage over time.

The API endpoint `GET /working-memory/file-snapshot` is canonical-first:

- reads canonical snapshot paths first
- falls back to legacy snapshot paths only when canonical is missing
- returns `path_mode` and source metadata for dashboard observability
