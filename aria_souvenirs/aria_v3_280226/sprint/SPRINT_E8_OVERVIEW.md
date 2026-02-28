# Sprint E8 — Focus-Aware Token Optimization

**Date:** 2026-02-28  
**Goal:** Wire focus levels (L1/L2/L3) into delegation + roundtable/swarm routing; eliminate ~1800 lines of always-loaded duplicate content from aria_mind.

## 5-Pass Investigation Summary

| Pass | Focus | Key Finding |
|------|-------|-------------|
| 1 | Token consumption | aria loads 8 files (~2200 lines); TOOLS+SKILLS 80% duplicate |
| 2 | Focus delegation | Focus→Skill table buried; delegation decision tree missing |
| 3 | Roundtable/Swarm | Trigger conditions undefined; sub-agents never know these modes exist |
| 4 | L1/L2/L3 levels | engine_focus.py exists but zero mind files reference focus levels |
| 5 | Context duplication | api_client/rules blocks appear 2–3× across files |

## Tickets

| Ticket | Title | Files Affected | Impact |
|--------|-------|----------------|--------|
| S-78 | HEARTBEAT — focus level check + L1/L2/L3 routing | HEARTBEAT.md | ~-120 tokens/cycle saved in L1 mode |
| S-79 | ORCHESTRATION.md — roundtable/swarm trigger conditions | ORCHESTRATION.md | Enables proper multi-agent use |
| S-80 | SKILLS.md lean — collapse to routing table + ref block | SKILLS.md | 274→~50 lines always-loaded |
| S-81 | TOOLS.md dedup — remove content duplicated from SKILLS.md | TOOLS.md | 225→~80 lines; canonical api_client rules |
| S-82 | GOALS.md lean — 5-step header only | GOALS.md | 219→~30 lines always-loaded |
| S-83 | SECURITY.md lean — 5 hard rules header only | SECURITY.md | 415→~25 lines always-loaded |
| S-84 | AGENTS.md lean — routing table only | AGENTS.md | 286→~35 lines always-loaded |
| S-85 | RPG.md lean — activation note only | RPG.md | 323→~20 lines always-loaded |
| S-86 | engine_focus wiring — work_cycle checks active focus profile | HEARTBEAT.md, aria_engine/ | L1/L2/L3 enables adaptive routing |

## Token Impact Estimate

| Before | After | Saving |
|--------|-------|--------|
| ~2728 always-loaded lines | ~350 always-loaded + ~2378 in Reference | ~87% reduction in context for delegated agents |
| aria main: 8 files full | aria main: 8 files lean headers | ~70% reduction |
| duplicated rules: 3× each | canonical location: 1× | 2 extra copies eliminated |
