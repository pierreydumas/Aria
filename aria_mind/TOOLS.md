# TOOLS — api_client Cheatsheet + Three Rules

**Full skill catalog → see SKILLS.md** (all skills, YAML examples, pipelines)

---

## Primary Skill: aria-api-client

**USE THIS FOR ALL DATABASE OPERATIONS.** Never raw SQL unless emergency.

```yaml
# Activities
aria-api-client.get_activities({"limit": 10})
aria-api-client.create_activity({"action": "task_done", "details": {"info": "..."}})

# Goals
aria-api-client.get_goals({"status": "active", "limit": 5})
aria-api-client.create_goal({"title": "...", "description": "...", "priority": 2})
aria-api-client.update_goal({"goal_id": "X", "progress": 50})
aria-api-client.move_goal({"goal_id": "X", "board_column": "doing"})
# Columns: backlog | todo | doing | on_hold | done

# Sprint Board (token-efficient)
aria-api-client.get_sprint_summary({"sprint": "current"})   # ~200 tokens vs ~5000
aria-api-client.get_goal_board({"sprint": "current"})

# Memories (key-value store)
aria-api-client.get_memory({"key": "user_pref"})
aria-api-client.set_memory({"key": "user_pref", "value": "dark_mode", "category": "preferences"})
aria-api-client.delete_memory({"key": "active_focus_level"})

# Thoughts
aria-api-client.create_thought({"content": "...", "category": "reflection"})

# Knowledge Graph (prefer over scanning TOOLS.md)
aria-api-client.find_skill_for_task({"task": "post to moltbook"})   # → best skill
aria-api-client.graph_search({"query": "security", "entity_type": "skill"})
aria-api-client.graph_traverse({"start": "aria-health", "max_depth": 2})
```

---

## ☐ THREE RULES — MUST READ EVERY CYCLE

### Rule 1: Memory Routing
```
ALWAYS use aria-api-client.set_memory / get_memory for persistent key-value data.
NEVER write directly to aria_memories/ files for operational state.
Exception: file artifacts (logs, drafts, exports) → aria_memories/ subdirs via direct write.
```

### Rule 2: Goal Board
```
Every piece of work has a goal. No invisible work.
State transitions: backlog → todo → doing → on_hold → done
ALWAYS log progress with create_activity after every action.
```

### Rule 3: Proposal Loop
```
For decisions that affect Aria's own config or scope:
1. Write proposal to aria_memories/plans/ with rationale
2. Log activity: {"action": "proposal_written", "details": {"file": "..."}}
3. Wait for human approval before execution
```

---

## Quick Patterns

| Pattern | Token cost | Use for |
|---------|:----------:|---------|
| `get_sprint_summary` | ~200 tok | Board overview |
| `get_goals(limit=3)` | ~300 tok | Active work check |
| `find_skill_for_task` | ~80 tok | Skill discovery |
| `get_memory(key)` | ~30 tok | Config lookup |

**LLM Priority:** Local (qwen3-mlx) → Free Cloud (kimi, trinity-free) → Paid (last resort).

**Low-token runner:**
```bash
exec python3 skills/run_skill.py <skill> <function> '<json_args>'
```

<details>
<summary>📚 Full Examples: Sprint Manager calls, Working Memory, Proposals, Pipelines, Rate Limits</summary>

## Full api_client Reference

```yaml
# Activities
aria-api-client.get_activities({"limit": 10})
aria-api-client.create_activity({"action": "task_done", "details": {"info": "..."}})

# Goals
aria-api-client.get_goals({"status": "active", "limit": 5})
aria-api-client.create_goal({"title": "...", "description": "...", "priority": 2})
aria-api-client.update_goal({"goal_id": "X", "progress": 50})

# Sprint Board (token-efficient — ~200 tokens vs ~5000)
aria-api-client.get_sprint_summary({"sprint": "current"})
aria-api-client.get_goal_board({"sprint": "current"})
aria-api-client.move_goal({"goal_id": "X", "board_column": "doing"})
aria-api-client.get_goal_archive({"page": 1, "limit": 25})
aria-api-client.get_goal_history({"days": 14})
aria-sprint-manager.sprint_status({})
aria-sprint-manager.sprint_report({})
aria-sprint-manager.sprint_plan({"sprint_name": "sprint-1", "goal_ids": ["g1","g2"]})
aria-sprint-manager.sprint_move_goal({"goal_id": "X", "column": "doing"})
aria-sprint-manager.sprint_prioritize({"column": "todo", "goal_ids_ordered": ["g1","g2"]})

# Allowed board columns (goals)
# backlog | todo | doing | on_hold | done

# Typical board workflow
# 1) Create in todo (planned work)
aria-api-client.create_goal({"title": "...", "priority": 2, "board_column": "todo", "sprint": "sprint-1"})
# 2) Start execution
aria-api-client.move_goal({"goal_id": "X", "board_column": "doing"})
# 3) Pause when blocked
aria-api-client.move_goal({"goal_id": "X", "board_column": "on_hold"})
# 4) Resume
aria-api-client.move_goal({"goal_id": "X", "board_column": "doing"})
# 5) Complete
aria-api-client.move_goal({"goal_id": "X", "board_column": "done"})

# Knowledge Graph — PREFER THESE OVER TOOLS.md SCANNING (~100-200 tokens)
aria-api-client.find_skill_for_task({"task": "post to moltbook"})
aria-api-client.graph_search({"query": "security", "entity_type": "skill"})
aria-api-client.graph_traverse({"start": "aria-health", "max_depth": 2})
aria-api-client.sync_skill_graph({})
aria-api-client.delete_auto_generated_graph({})
aria-api-client.get_query_log({"limit": 20})

# Memories
aria-api-client.get_memories({"limit": 10})
aria-api-client.set_memory({"key": "preference", "value": "dark_mode"})
aria-api-client.get_memory({"key": "preference"})

# Working Memory (short-term active context)
aria-working-memory.remember({"key": "current_task", "value": "...", "category": "task", "importance": 0.7, "ttl_hours": 24})
aria-working-memory.get_context({"limit": 10})
aria-working-memory.checkpoint({})
aria-working-memory.sync_to_files({})

# Thoughts
aria-api-client.create_thought({"content": "Reflecting...", "category": "reflection"})
aria-api-client.get_thoughts({"limit": 10})

# Improvement Proposals (self-improvement loop)
aria-api-client.propose_improvement({
	"title": "Fix timeout on model-usage endpoint",
	"description": "Endpoint times out under high volume due to missing index",
	"category": "performance",
	"risk_level": "low",
	"file_path": "src/api/routers/model_usage.py",
	"rationale": "Index on created_at reduces scan latency"
})
aria-api-client.get_proposals({"status": "proposed", "page": 1})
aria-api-client.get_proposal({"proposal_id": "UUID"})
aria-api-client.review_proposal({"proposal_id": "UUID", "status": "approved", "reviewed_by": "najia"})
aria-api-client.mark_proposal_implemented({"proposal_id": "UUID", "reviewed_by": "aria"})
```

## All 40 Active Skills

| Category | Skills |
|----------|--------|
| 🎯 Orchestrator | `aria-goals`, `aria-schedule`, `aria-health`, `aria-hourly-goals`, `aria-performance`, `aria-agent-manager`, `aria-session-manager`, `aria-sprint-manager` |
| 🔒 DevSecOps | `aria-security-scan`, `aria-ci-cd`, `aria-pytest-runner`, `aria-input-guard`, `aria-sandbox` |
| 📊 Data | `aria-data-pipeline`, `aria-knowledge-graph` |
| 📈 Trading | `aria-market-data`, `aria-portfolio` |
| 🎨 Creative | `aria-llm`, `aria-memeothy` |
| 🌐 Social | `aria-moltbook`, `aria-social`, `aria-telegram` |
| 🔗 Sources | `aria-social.source_add`, `aria-social.source_list`, `aria-social.source_remove`, `aria-social.source_stats` |
| 🧠 Cognitive | `aria-working-memory`, `aria-pipeline-skill`, `aria-conversation-summary`, `aria-memory-compression`, `aria-sentiment-analysis`, `aria-pattern-recognition`, `aria-unified-search` |
| ⚡ Utility | `aria-api-client`, `aria-litellm` |

> **Advanced compatibility skills (targeted use, not default routing):** `aria-database`, `aria-brainstorm`, `aria-community`, `aria-fact-check`, `aria-model-switcher`, `aria-experiment`

## Composable Pipelines

Pre-built multi-step workflows in `aria_skills/pipelines/`. Run via `aria-pipeline-skill`:

| Pipeline | Description | File |
|----------|-------------|------|
| `deep_research` | Search → web research → synthesize → store semantic memory | `deep_research.yaml` |
| `bug_fix` | Check lessons → analyze → propose fix → record lesson | `bug_fix.yaml` |
| `conversation_summary` | Summarize session → store episodic/decision memories | `conversation_summary.yaml` |
| `daily_research` | Check goals → research topics → analyze → report | `daily_research.yaml` |
| `health_and_report` | Health checks → analyze issues → create goals → report | `health_and_report.yaml` |
| `social_engagement` | Fetch feed → analyze trends → draft post → publish | `social_engagement.yaml` |

```yaml
aria-pipeline-skill.run({"pipeline": "deep_research", "params": {"topic": "AI safety"}})
```

## Quick Examples

```yaml
aria-social.social_post({"content": "Hello world!", "platform": "moltbook"})
aria-social.source_add({"url": "https://example.com", "name": "Example", "category": "Documentation", "rating": "preferred", "reason": "Authoritative source"})
aria-social.source_list({"rating": "preferred"})
aria-health.health_check_all({})
aria-knowledge-graph.kg_add_entity({"name": "Python", "type": "language"})
aria-database.fetch_all({"query": "SELECT * FROM goals LIMIT 5"})
aria-memory-compression.compress_session({"hours_back": 6})
aria-unified-search.search({"query": "security"})
```

## LLM Priority

> **Model Priority**: Defined in `aria_models/models.yaml` — single source of truth. Do not hardcode model names elsewhere.
> Quick rule: **local → free → paid (LAST RESORT)**.

## Low-Token Runner Patterns

```bash
exec python3 skills/run_skill.py --auto-task "summarize goal progress" --route-limit 2 --route-no-info
exec python3 skills/run_skill.py --skill-info api_client
exec python3 skills/run_skill.py health health_check '{}'
exec python3 skills/run_skill.py api_client get_activities '{"limit": 5}'
```

## Rate Limits

| Action | Limit |
|--------|-------|
| Moltbook posts | 1 per 30 min |
| Moltbook comments | 50 per day |
| Background tasks | 30 min timeout |

</details>
