# SPRINT ORCHESTRATOR — E7 + E8 Self-Executing Agent Prompt
**Hand this file + all 17 ticket files to a single Claude session.**  
**The session IS the orchestrator. It spawns no external agents — it executes sub-tasks itself using bash and file tools.**

---

## Role

You are the sprint execution orchestrator for the Aria project.  
Your job: execute all 17 tickets from Epic E7 + E8 in dependency order, verify each one, and report a per-ticket status table at the end.

You have full access to:
- Bash (read files, run Python, run curl, apply diffs)
- File creation and editing tools
- The ticket files in `aria_souvenirs/aria_v3_280226/sprint/`

**Do not ask for permission. Do not summarize what you plan to do. Execute.**

---

## Hard Rules

1. **Never proceed past a failed gate.** If a gate command returns unexpected output, stop that phase, report the failure, and wait for instruction.
2. **Never modify `aria_mind/soul/` files** unless a ticket explicitly names a soul file as the target.
3. **Read the ticket file before executing it.** Use the BEFORE/AFTER blocks exactly as written. Do not paraphrase or re-derive them.
4. **No direct DB access from skill layer.** Skills call REST API only.
5. **Verification is mandatory.** Run every numbered verification command in the ticket. Do not mark a ticket done until all return EXPECTED output.
6. **Syntax check every Python file you create or modify** before moving to the next ticket.

---

## Execution Model

You execute phases, not individual tickets. Within a phase, independent tickets are run sequentially (you are one agent). Between phases, you run the phase gate before starting the next phase.

```
Phase 1 → Phase Gate 1 → Phase 2 → Phase Gate 2 → Phase 3 → Phase Gate 3 → Phase 4 → Phase Gate 4 → DONE
```

---

## Phase 1 — Mind File Optimization (no dependencies, do this first)

**Tickets (run in any order — all independent):**

| Order | Ticket | File | Description |
|:-----:|--------|------|-------------|
| 1 | E8-S80 | E8-S80-aaa.md | SKILLS.md lean refactor |
| 2 | E8-S81 | E8-S81-aaa.md | TOOLS.md dedup |
| 3 | E8-S82 | E8-S82-aaa.md | GOALS.md lean refactor |
| 4 | E8-S83 | E8-S83-aaa.md | SECURITY.md lean refactor |
| 5 | E8-S84 | E8-S84-aaa.md | AGENTS.md lean refactor |
| 6 | E8-S85 | E8-S85-aaa.md | RPG.md lean refactor |
| 7 | E8-S78 | E8-S78-aaa.md | HEARTBEAT.md — L1/L2/L3 focus docs |
| 8 | E8-S79 | E8-S79-aaa.md | ORCHESTRATION.md — roundtable triggers |

**For each ticket:**
1. `cat aria_souvenirs/aria_v3_280226/sprint/<TICKET>-aaa.md` — read fully
2. Apply changes as specified (these are all markdown file edits in `aria_mind/`)
3. Run verification commands from the ticket
4. Mark ✅ or ❌

### Phase Gate 1
```bash
# All 8 mind files must exist and be modified
for f in \
  aria_mind/SKILLS.md aria_mind/TOOLS.md aria_mind/GOALS.md aria_mind/SECURITY.md \
  aria_mind/AGENTS.md aria_mind/RPG.md aria_mind/HEARTBEAT.md aria_mind/ORCHESTRATION.md; do
  echo "$f: $(wc -l < $f) lines"
done
# EXPECTED: all files exist and line counts are <= original counts (lean = shorter)
```

---

## Phase 2 — DB Foundation (hard dependency chain begins)

**Tickets (must run in this exact order):**

| Order | Ticket | File | Gate Before |
|:-----:|--------|------|-------------|
| 1 | E7-S70 | E7-S70-aaa.md | none |
| 2 | E7-S71 | E7-S71-aaa.md | S70 gate below |

### S70 Gate (run before S71)
```bash
# ORM class exists
grep -n "class FocusProfileEntry" src/api/db/models.py | head -1
# EXPECTED: line number + "class FocusProfileEntry"

# Table exists in DB
docker exec aria-db psql -U admin -d aria_warehouse -c "\dt aria_engine.focus_profiles"
# EXPECTED: table "focus_profiles" listed

# to_dict() returns expected keys
docker exec aria-api python3 -c "
from db.models import FocusProfileEntry
import inspect
src = inspect.getsource(FocusProfileEntry.to_dict)
required = ['focus_id','token_budget_hint','delegation_level','system_prompt_addon','temperature_delta','expertise_keywords']
for k in required:
    assert k in src, f'MISSING: {k}'
print('S70 GATE PASS')
"
# EXPECTED: S70 GATE PASS
```

### S71 Gate (run before Phase 3)
```bash
# Router file exists
test -f src/api/routers/engine_focus.py && echo "EXISTS" || echo "MISSING"
# EXPECTED: EXISTS

# Router registered in main.py
grep -n "engine_focus_router" src/api/main.py
# EXPECTED: 3 lines (relative import, absolute import, include_router)

# API responds
curl -s http://localhost/api/engine/focus | python3 -c "
import sys, json
d = json.load(sys.stdin)
profiles = d.get('profiles', d) if isinstance(d, dict) else d
print(f'profiles: {len(profiles)}')
assert len(profiles) >= 8, f'Expected 8, got {len(profiles)}'
print('S71 GATE PASS')
"
# EXPECTED: profiles: 8 / S71 GATE PASS
```

---

## Phase 3 — Engine Layer (4 parallel-eligible tickets behind S71)

**Tickets (S72/S73/S74/S76 all depend only on S71 — run sequentially):**

| Order | Ticket | File | Notes |
|:-----:|--------|------|-------|
| 1 | E7-S72 | E7-S72-aaa.md | routing.py DB-driven cache |
| 2 | E7-S73 | E7-S73-aaa.md | **@dataclass** — read CRITICAL note before touching agent_pool.py |
| 3 | E7-S74 | E7-S74-aaa.md | token budget cap (depends on S73 _focus_profile field) |
| 4 | E7-S76 | E7-S76-aaa.md | HTML UI — do nav wiring step AFTER reading base.html |

**Special instruction for E7-S73:**
Before applying any edit to `aria_engine/agent_pool.py`, run:
```bash
sed -n '44,50p' aria_engine/agent_pool.py
# MUST see: @dataclass on the line before "class EngineAgent"
# If you do NOT see @dataclass: STOP and report. Do not apply the ticket.
```

**Special instruction for E7-S76 nav wiring:**
Before applying nav edits, run these to get actual line numbers:
```bash
grep -n "operations/health\|render_template('engine_health" src/web/app.py | head -3
grep -n "Sessions.*request.path\|/sessions.*in request" src/web/templates/base.html | head -3
grep -n "nav-dropdown-toggle.*chat.*agent-manager" src/web/templates/base.html | head -3
```
Use these actual lines to place the inserts, not the approximate line numbers in the ticket.

### Phase Gate 3
```bash
# routing.py loads from DB
docker exec aria-api python3 -c "
from aria_engine.routing import EngineRouter
# EngineRouter must have initialize_patterns coroutine
import inspect, asyncio
assert hasattr(EngineRouter, 'initialize_patterns'), 'initialize_patterns missing'
print('S72 routing PASS')
"
# EXPECTED: S72 routing PASS

# EngineAgent has _focus_profile field (NOT a crash)
docker exec aria-api python3 -c "
import dataclasses
from aria_engine.agent_pool import EngineAgent
fields = {f.name for f in dataclasses.fields(EngineAgent)}
assert '_focus_profile' in fields, f'_focus_profile not a dataclass field — CRASH RISK'
print('S73 dataclass PASS')
"
# EXPECTED: S73 dataclass PASS

# token cap applied
docker exec aria-api python3 -c "
from aria_engine.agent_pool import EngineAgent
import dataclasses
# create a minimal agent and check _budget_cap exists or budget logic present
import inspect
src = inspect.getsource(EngineAgent.process)
assert 'budget_cap' in src or 'token_budget' in src or '_budget' in src, 'budget cap not found in process()'
print('S74 token cap PASS')
"
# EXPECTED: S74 token cap PASS

# UI template exists
test -f src/web/templates/engine_focus.html && echo "S76 template PASS" || echo "S76 MISSING"
# EXPECTED: S76 template PASS

# Route registered
grep -c "operations/focus" src/web/app.py
# EXPECTED: >= 2
```

---

## Phase 4 — Wiring + Skill (depend on S71+S73)

**Tickets (run in this order):**

| Order | Ticket | File | Notes |
|:-----:|--------|------|-------|
| 1 | E7-S75 | E7-S75-aaa.md | roundtable auto-select (depends S72, S73) |
| 2 | E8-S86 | E8-S86-aaa.md | heartbeat wiring (depends S71, S78) |
| 3 | E7-S77 | E7-S77-aaa.md | focus skill (depends S71, S73) |

**Special instruction for E7-S75:**
Before editing `aria_engine/roundtable.py`, run:
```bash
grep -n "async def discuss" aria_engine/roundtable.py
sed -n '136,148p' aria_engine/roundtable.py
# Confirm discuss() signature matches what the ticket expects
```

### Phase Gate 4 — Sprint Complete
```bash
# roundtable discuss() accepts optional agent_ids
docker exec aria-api python3 -c "
import inspect
from aria_engine.roundtable import Roundtable
sig = inspect.signature(Roundtable.discuss)
params = list(sig.parameters)
assert 'agent_ids' in params, f'agent_ids not in discuss() params: {params}'
print('S75 roundtable PASS — params:', params)
"
# EXPECTED: S75 roundtable PASS

# heartbeat reads focus_level
docker exec aria-api python3 -c "
import pathlib
src = pathlib.Path('aria_mind/heartbeat.py').read_text()
assert 'focus_level' in src or 'delegation_level' in src, 'focus_level not in heartbeat'
print('S86 heartbeat PASS')
"
# EXPECTED: S86 heartbeat PASS

# focus skill syntax clean
docker exec aria-api python3 -c "
import ast, pathlib
ast.parse(pathlib.Path('aria_skills/focus/__init__.py').read_text())
print('S77 syntax PASS')
"
# EXPECTED: S77 syntax PASS

# focus skill registers
docker exec aria-api python3 -c "
from aria_skills.focus import FocusSkill
from aria_skills.registry import SkillRegistry
s = SkillRegistry.get('focus')
assert s is not None, 'focus skill not registered'
print('S77 registry PASS')
"
# EXPECTED: S77 registry PASS
```

---

## Final Status Report

When all 4 phase gates pass, output this table filled in:

```
## Sprint E7+E8 Execution Report
Date: <date>

| Ticket | Title | Status | Notes |
|--------|-------|:------:|-------|
| E8-S80 | SKILLS.md lean | ✅/❌ | |
| E8-S81 | TOOLS.md dedup | ✅/❌ | |
| E8-S82 | GOALS.md lean | ✅/❌ | |
| E8-S83 | SECURITY.md lean | ✅/❌ | |
| E8-S84 | AGENTS.md lean | ✅/❌ | |
| E8-S85 | RPG.md lean | ✅/❌ | |
| E8-S78 | HEARTBEAT.md L1/L2/L3 | ✅/❌ | |
| E8-S79 | ORCHESTRATION.md triggers | ✅/❌ | |
| E7-S70 | FocusProfileEntry ORM | ✅/❌ | |
| E7-S71 | engine_focus.py CRUD | ✅/❌ | |
| E7-S72 | routing.py DB-driven | ✅/❌ | |
| E7-S73 | agent_pool.py focus composition | ✅/❌ | |
| E7-S74 | token budget cap | ✅/❌ | |
| E7-S76 | engine_focus.html UI | ✅/❌ | |
| E7-S75 | roundtable auto-select | ✅/❌ | |
| E8-S86 | heartbeat.py wiring | ✅/❌ | |
| E7-S77 | focus skill | ✅/❌ | |

**Gates passed:** <n>/4
**Tickets complete:** <n>/17
```

Then run:
```bash
cd /Users/najia/aria && git add -A && git commit -m "sprint E7+E8: execution complete — <n>/17 tickets done"
```

---

## Context Files (read in this order at session start)

```
aria_souvenirs/aria_v3_280226/sprint/SPRINT_FINAL_MASTER.md   ← dependency graph + roster
aria_souvenirs/aria_v3_280226/sprint/E8-S80-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E8-S81-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E8-S82-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E8-S83-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E8-S84-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E8-S85-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E8-S78-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E8-S79-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E7-S70-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E7-S71-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E7-S72-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E7-S73-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E7-S74-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E7-S76-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E7-S75-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E8-S86-aaa.md
aria_souvenirs/aria_v3_280226/sprint/E7-S77-aaa.md
```

---

## Failure Protocol

If any gate fails:
1. Print: `GATE FAILURE — Phase <N> — <ticket> — <command> returned: <actual output>`
2. Print: `BLOCKER: <root cause in one sentence>`
3. Stop execution of dependent tickets
4. Continue executing tickets in the current phase that are NOT blocked
5. Skip dependent phases but complete independent ones
6. Include all failures in the final status table

Do NOT hallucinate a pass. Do NOT retry more than once without reporting.
