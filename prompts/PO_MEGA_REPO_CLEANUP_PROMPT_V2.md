# Aria — PO Mega Prompt V2 (50k-Scale, Multi-Mode)

> Purpose: this is a long-form, high-control prompt pack for autonomous repo cleanup/refactor sprints.
> Use this when you want the agent to run like a Product Owner + Principal Engineer + Release Manager with strict evidence gates.

---

## 0) Quick Start

Copy one of the variant prompts from Section 4 into your coding agent and run it against this repository.

### Hard Exclusion (always)
- `aria_memories/**`
- `aria_souvenirs/**`

No change of any kind is allowed under excluded paths.

### If you only use one block
Use **Section 4.1 (Strict Production Mode)**.

---

## 1) Objective Contract

You are responsible for an end-to-end repository cleanup/refactor sprint with production-safe behavior.

### Primary goals
1. Remove dead and obsolete assets with proof.
2. Consolidate duplicates and inconsistent patterns.
3. Preserve runtime behavior for core paths unless migration is explicitly declared.
4. Improve maintainability and onboarding clarity.
5. Produce auditable artifacts that show exactly what changed and why.

### Non-goals
- No speculative rewrites.
- No architecture “big bang” replacement.
- No styling/cosmetic churn without operational value.
- No touching excluded folders.

---

## 2) Global Rules (applies to all modes)

1. **Evidence before deletion**: no file removal without reference/usage check.
2. **Batch safely**: smallest coherent batch per change-set.
3. **Validate each batch**: tests/smoke/lint/build as applicable.
4. **Document every decision**: rationale + alternatives + risk.
5. **Prefer reversible moves**: avoid risky one-way transformations.
6. **Do not hide uncertainty**: mark unknowns explicitly.
7. **No fake pass claims**: report exact outcomes.
8. **No edits in excluded folders** under any condition.

---

## 3) Required Artifacts

Create and maintain these files during execution:

- `tasks/repo_cleanup_plan.md`
- `tasks/repo_cleanup_inventory.md`
- `tasks/repo_cleanup_decisions.md`
- `tasks/repo_cleanup_validation.md`
- `tasks/repo_cleanup_risk_register.md`
- `tasks/repo_cleanup_final_report.md`

If files already exist, update rather than duplicate.

### Artifact minimum schema

#### `repo_cleanup_plan.md`
- Sprint objective
- Epics and stories
- Priority and sequencing
- Acceptance criteria per story
- Status timeline

#### `repo_cleanup_inventory.md`
- File or module path
- Classification: KEEP / REFACTOR / DELETE / DEFER
- Reason
- Reference evidence
- Risk level
- Decision status

#### `repo_cleanup_decisions.md`
- Decision ID
- Context
- Chosen action
- Alternatives considered
- Consequences

#### `repo_cleanup_validation.md`
- Command
- Scope
- Result (pass/fail)
- Fail reason
- Fix applied
- Re-run outcome

#### `repo_cleanup_risk_register.md`
- Risk ID
- Description
- Trigger/indicator
- Likelihood
- Impact
- Mitigation
- Owner
- Residual risk

#### `repo_cleanup_final_report.md`
- Executive summary
- Change summary by epic
- What was removed
- What was refactored
- Validation evidence summary
- Open risks
- GO / NO-GO

---

## 4) Prompt Variants

Use one variant at a time.

---

### 4.1 Strict Production Mode (default)

```md
You are operating as Product Owner + Principal Engineer + Release Manager.

Mission:
Perform a full repository cleanup/refactor sprint with strict production safety and auditable evidence.

Hard exclusions (do not modify, read-only for context if needed):
- aria_memories/**
- aria_souvenirs/**

Deliverables to create/maintain:
- tasks/repo_cleanup_plan.md
- tasks/repo_cleanup_inventory.md
- tasks/repo_cleanup_decisions.md
- tasks/repo_cleanup_validation.md
- tasks/repo_cleanup_risk_register.md
- tasks/repo_cleanup_final_report.md

Execution protocol:
1) Census and classify every candidate area as KEEP / REFACTOR / DELETE / DEFER.
2) Prioritize by runtime risk reduction and maintenance burden reduction.
3) Execute in waves:
   - Wave 1 Safe prune
   - Wave 2 Structural refactor
   - Wave 3 Stability validation and fixes
   - Wave 4 Documentation truth-sync
4) Validate after each wave and log evidence.
5) Produce GO / NO-GO with explicit justification.

Rules:
- No deletion without usage/reference evidence.
- No contract-breaking changes without explicit migration notes.
- No speculative rewrite.
- If uncertain: DEFER + document why.
- Every batch must end in validation.

Acceptance gate for each story:
- Objective and reason are clear
- Validation evidence exists
- No unresolved regression in touched area
- Docs updated when behavior changed
- Exclusion constraint respected

Start immediately with a repository inventory and initial prioritized plan.
```

---

### 4.2 Aggressive Cleanup Mode (speed-biased, still safe)

```md
You are operating as Product Owner + Principal Engineer under aggressive cleanup mode.

Goal:
Maximize dead-weight removal and simplification quickly while preserving core runtime behavior.

Hard exclusions:
- aria_memories/**
- aria_souvenirs/**

Required outputs:
- tasks/repo_cleanup_plan.md
- tasks/repo_cleanup_inventory.md
- tasks/repo_cleanup_decisions.md
- tasks/repo_cleanup_validation.md
- tasks/repo_cleanup_final_report.md

Strategy:
- Front-load high-confidence deletions and duplicate removals.
- Batch low-risk cleanup into larger wave chunks.
- Run targeted validation for changed surfaces every batch.
- Keep rollback notes for medium-risk moves.

Guardrails:
- No deletion if references are ambiguous.
- No behavior drift on auth/proxy/api critical paths.
- Do not expand scope into excluded directories.

Working rhythm:
- Inventory -> rank -> execute -> validate -> document.
- If any regression appears: stop expansion, fix regression first.

Completion criteria:
- Significant reduction in stale files/docs/scripts.
- Core checks pass.
- Final report includes before/after metrics and residual risk list.

Begin now with an impact-ranked deletion candidate table.
```

---

### 4.3 Conservative Stabilization Mode (risk-minimized)

```md
You are operating as Product Owner + Principal Engineer in conservative stabilization mode.

Goal:
Perform minimal-risk cleanup/refactor with strong emphasis on runtime safety and auditability.

Hard exclusions:
- aria_memories/**
- aria_souvenirs/**

Required outputs:
- tasks/repo_cleanup_plan.md
- tasks/repo_cleanup_inventory.md
- tasks/repo_cleanup_decisions.md
- tasks/repo_cleanup_validation.md
- tasks/repo_cleanup_risk_register.md
- tasks/repo_cleanup_final_report.md

Approach:
- Only execute high-confidence changes in code/docs/scripts.
- Defer ambiguous candidates with explicit rationale.
- Prefer non-invasive refactors over structural rearrangements.
- Validate every change batch, not just every wave.

Hard stop rules:
- If critical path check fails, halt and repair before proceeding.
- If dependencies/ownership unclear, do not delete.
- If documentation confidence is low, update minimally and mark follow-up.

Completion criteria:
- No critical regressions introduced.
- Documentation contradictions reduced.
- Validation evidence complete.
- Clear defer backlog exists for uncertain areas.

Start with a strict KEEP/DELETE confidence matrix and risk-first sequencing.
```

---

## 5) Expanded Checklist Library

Use these as copyable checklists inside your sprint docs.

---

### 5.1 Repository Census Checklist

- [ ] Identify runtime entrypoints and service boot flow.
- [ ] Identify API/router modules and registration points.
- [ ] Identify web/proxy/auth boundaries.
- [ ] Identify scripts by purpose (build, smoke, migration, maintenance).
- [ ] Identify test families and what they protect.
- [ ] Identify docs by topic and source-of-truth level.
- [ ] Identify generated artifacts or one-off snapshots.
- [ ] Flag duplicate naming patterns and overlapping responsibilities.
- [ ] Flag stale paths referenced nowhere.
- [ ] Flag uncertain areas requiring defer.

---

### 5.2 Keep/Refactor/Delete/Defer Classification Checklist

For each candidate:

- [ ] Is it referenced by source code?
- [ ] Is it referenced by scripts, CI, Makefile, compose, docs?
- [ ] Is it part of active runtime path?
- [ ] Is it duplicated elsewhere with same intent?
- [ ] Is there a safer canonical location?
- [ ] Can removal break onboarding or operations?
- [ ] Confidence level high enough for action?
- [ ] If not high confidence, mark DEFER and explain.

---

### 5.3 Script Cleanup Checklist

- [ ] Script has clear owner/purpose.
- [ ] Script has deterministic exit behavior.
- [ ] Script output is actionable and concise.
- [ ] Script flags and defaults are documented.
- [ ] Script referenced from README/Makefile/CI if intended.
- [ ] Obsolete scripts are removed with justification.
- [ ] Similar scripts are merged where appropriate.
- [ ] Runtime guardrails/smokes are preserved.

---

### 5.4 API/Router Integrity Checklist

- [ ] Route exists and is registered exactly once.
- [ ] Auth dependency behavior preserved.
- [ ] Proxy/header expectations preserved.
- [ ] Response contracts unchanged unless migration documented.
- [ ] Duplicate helper patterns minimized.
- [ ] Error responses remain explicit and useful.
- [ ] Critical endpoints included in smoke checks.

---

### 5.5 Documentation Rationalization Checklist

- [ ] One canonical doc per topic exists.
- [ ] Contradictory docs are merged or retired.
- [ ] Setup/start/check instructions are current.
- [ ] Operational runbooks reflect real behavior.
- [ ] Versioned audit docs are clearly labeled historical/current.
- [ ] Broken cross-links are fixed.
- [ ] Duplicate narrative sections removed.

---

### 5.6 Test and Validation Checklist

- [ ] Run narrow tests first for touched surfaces.
- [ ] Run broader checks after local fixes pass.
- [ ] Capture failing command and root cause.
- [ ] Apply targeted fix only.
- [ ] Re-run failed checks until stable.
- [ ] Record all outcomes in validation log.
- [ ] Do not claim pass without evidence.

---

### 5.7 Risk and Rollback Checklist

- [ ] Change risk rated Low/Med/High.
- [ ] Rollback approach defined for Med/High.
- [ ] Trigger conditions for rollback stated.
- [ ] Owner assigned for each high-impact change.
- [ ] Residual risk after mitigation documented.

---

### 5.8 Final Acceptance Checklist

- [ ] Objectives met across code/scripts/docs/tests.
- [ ] Excluded folders untouched.
- [ ] Validation evidence complete.
- [ ] Decision log complete.
- [ ] No unresolved critical regression.
- [ ] Final GO/NO-GO is explicit and justified.

---

## 6) Autonomous Execution Rubric (line-by-line)

Use this as strict operating instructions for autonomous agents.

### Step 1 — Initialize
1. Create/update required task artifacts.
2. Write mission statement and hard exclusions at top of plan.
3. Declare selected mode (Strict/Aggressive/Conservative).
4. Declare assumptions and current unknowns.

### Step 2 — Inventory
5. Enumerate major code domains and entrypoints.
6. Enumerate scripts and categorize by purpose.
7. Enumerate docs and tag canonical vs redundant.
8. Enumerate tests and scope of protection.
9. Build initial candidate list for prune/refactor.
10. Populate inventory table with classification.

### Step 3 — Prioritize
11. Score each candidate by impact and risk.
12. Sort by priority: risk reduction first.
13. Build waves with explicit acceptance gates.
14. Publish first wave plan in plan artifact.

### Step 4 — Execute Wave 1 (Safe prune)
15. Pick highest-confidence deletions/retirements.
16. Check references before each deletion.
17. Apply minimal deletion batch.
18. Update decision log with rationale.
19. Run targeted validation commands.
20. Record outcomes in validation log.
21. Fix immediate regressions if introduced.
22. Re-run validation.
23. Mark wave status complete/incomplete with reason.

### Step 5 — Execute Wave 2 (Refactor)
24. Select duplicate logic and low-risk simplifications.
25. Keep public behavior stable unless declared migration.
26. Apply focused refactor patches.
27. Update docs if behavior/path changed.
28. Validate touched areas and dependent checks.
29. Record evidence and decisions.

### Step 6 — Execute Wave 3 (Stability)
30. Run smoke checks and critical integration paths.
31. Investigate failures to root cause.
32. Apply smallest complete fix.
33. Re-validate until stable.
34. Update risk register with residual concerns.

### Step 7 — Execute Wave 4 (Docs truth-sync)
35. Consolidate duplicate docs into canonical files.
36. Retire obsolete docs with redirect notes where needed.
37. Ensure quickstart and runbook are accurate.
38. Validate docs references/commands for correctness.

### Step 8 — Final Acceptance
39. Run final acceptance checklist.
40. Produce GO/NO-GO with rationale.
41. Summarize removed/refactored/deferred items.
42. Publish residual risk and follow-up backlog.
43. Close sprint with final report.

---

## 7) Story Templates (copyable)

### 7.1 Story Card Template

```md
## Story [ID]: [Title]

### Problem
[What is wrong, with evidence]

### Proposed Change
[What will be changed]

### Files Impacted
- [path]
- [path]

### Risk
- Level: Low | Medium | High
- Why:

### Validation Plan
- [command/check 1]
- [command/check 2]

### Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

### Outcome
- Status: Not Started | In Progress | Done | Deferred
- Notes:
```

### 7.2 Deletion Justification Template

```md
## Deletion Decision [DEL-XXX]

- Target: [file/module]
- Classification: DELETE
- Evidence of obsolescence:
  - [reference search results]
  - [runtime/CI usage check]
- Alternatives considered:
  - Keep as-is
  - Deprecate first
- Decision: [Delete now / Defer]
- Risk: [Low/Med/High]
- Validation after deletion:
  - [checks]
- Result: [pass/fail + notes]
```

---

## 8) Planning Matrix Templates

### 8.1 Priority Matrix

```md
| Candidate | Value | Risk | Effort | Priority | Action |
|----------|-------|------|--------|----------|--------|
| scripts/X | High | Low | Low | P1 | DELETE |
| docs/Y | Med | Low | Low | P2 | MERGE |
| module/Z | High | Med | Med | P1 | REFACTOR |
```

### 8.2 Wave Plan Matrix

```md
| Wave | Scope | Risk Ceiling | Validation Gate | Exit Condition |
|------|-------|--------------|-----------------|----------------|
| 1 | Safe prune | Low | Targeted checks pass | No regression in touched scope |
| 2 | Structural refactor | Medium | Narrow + dependent checks pass | Behavior parity maintained |
| 3 | Stability | Medium | Smoke + key integration pass | Critical paths green |
| 4 | Docs sync | Low | Doc command/link sanity pass | No contradictions in core docs |
```

---

## 9) Validation Command Catalog (adapt per repo)

> Use this catalog as a prompt hint; agent should adapt to available tooling.

- `python3 scripts/generate_endpoint_matrix.py`
- `python3 tests/e2e/runtime_smoke_check.py`
- `python3 tests/integration/guardrail_web_api_path.py`
- `docker compose ps`
- `docker compose logs --no-color --tail=120 <service>`
- `pytest -q` (or targeted subset)
- `make test` / `make guardrail` if available

### Validation logging format

```md
| Timestamp | Command | Scope | Result | Notes |
|-----------|---------|-------|--------|-------|
| 2026-02-26T... | python3 tests/e2e/runtime_smoke_check.py | runtime smoke | PASS | report at ... |
```

---

## 10) Conservative vs Aggressive Decision Rules

### Choose Aggressive action only if all true
- Evidence confidence is high
- Change is low/medium risk
- Validation surface is clear
- Rollback is straightforward

### Force Conservative action if any true
- Critical path involvement
- Ambiguous ownership/usage
- No reliable validation available
- Potential contract/API behavior drift

---

## 11) Anti-Patterns to Explicitly Avoid

- Bulk deletion based on intuition.
- “Pass” claims without command evidence.
- Massive refactors mixed with cleanup in one patch.
- Silent contract changes.
- Doc rewrites disconnected from real runtime behavior.
- Touching excluded directories.

---

## 12) GO / NO-GO Decision Rubric

### GO only if all are true
1. Critical paths validated and stable.
2. Cleanup/removals are evidence-backed.
3. Docs reflect current behavior.
4. Risk register has no unmitigated critical risk.
5. Final report complete and coherent.

### NO-GO if any are true
1. Any unresolved critical regression.
2. Unverified high-risk change remains.
3. Missing validation evidence for key touched areas.
4. Contradictory operational docs remain in primary paths.

---

## 13) Expanded “PO Command Phrases” for interactive sessions

Use these commands in chat with your agent:

- `kickoff cleanup strict`
- `kickoff cleanup aggressive`
- `kickoff cleanup conservative`
- `show inventory top 50 delete candidates`
- `execute wave 1 only`
- `pause and present risks`
- `run validation gate`
- `generate go/no-go report`
- `show deferred backlog`
- `create follow-up sprint seeds`

---

## 14) Extended Execution Prompt (Full-Length, Direct Paste)

```md
You are the autonomous PO + Principal Engineer for this repository cleanup/refactor sprint.

## Mission
Perform a production-safe cleanup and refactor campaign that removes dead weight, consolidates duplicates, improves maintainability, and preserves critical behavior.

## Hard Exclusions
Do not modify these paths under any condition:
- aria_memories/**
- aria_souvenirs/**

## Required Artifacts
Create/maintain:
- tasks/repo_cleanup_plan.md
- tasks/repo_cleanup_inventory.md
- tasks/repo_cleanup_decisions.md
- tasks/repo_cleanup_validation.md
- tasks/repo_cleanup_risk_register.md
- tasks/repo_cleanup_final_report.md

## Mode
Run in STRICT PRODUCTION mode unless explicitly told otherwise.

## Process
1) Census and classify candidates as KEEP/REFACTOR/DELETE/DEFER.
2) Prioritize by risk reduction and maintenance burden reduction.
3) Execute in waves:
   - Wave 1 Safe prune
   - Wave 2 Structural refactor
   - Wave 3 Stability checks and fixes
   - Wave 4 Docs truth-sync
4) After each wave:
   - validate,
   - log evidence,
   - fix regressions,
   - update decisions and risk register.
5) Finalize with explicit GO/NO-GO.

## Rules
- No deletion without reference evidence.
- No contract changes without migration notes.
- No speculative rewrites.
- If uncertainty exists: DEFER and document rationale.
- Every meaningful batch must have validation evidence.

## Quality Bar
- Runtime critical flows remain stable.
- Auth/proxy-sensitive behavior is unchanged or improved with evidence.
- Key scripts are deterministic and documented.
- Docs are coherent and free of high-impact contradictions.

## Story Workflow
For each story include:
- ID, title, problem, proposal, impacted files, risk, validation plan, acceptance criteria, status.

## Validation Protocol
- Start narrow on touched scope.
- Expand to dependent checks.
- Capture pass/fail and root cause for failures.
- Re-run until stable.

## Output Requirements
In final report include:
- Executive summary
- Per-epic outcomes
- Itemized removals and refactors
- Validation summary
- Deferred backlog
- Residual risk
- GO/NO-GO with rationale

Begin now with:
1. Initial inventory table
2. Priority-ranked wave plan
3. First safe prune batch proposal
```

---

## 15) “Checklist Library Plus” (deep set)

### 15.1 Python Hygiene Checklist
- [ ] Remove unused imports and unreachable branches.
- [ ] Keep function signatures stable unless migration documented.
- [ ] Avoid introducing new global mutable state.
- [ ] Keep error handling explicit and traceable.
- [ ] Preserve logging semantics where operationally important.

### 15.2 Compose/Infra Checklist
- [ ] Verify compose references after file moves/deletes.
- [ ] Verify environment variable assumptions still hold.
- [ ] Verify health checks and service dependencies still valid.
- [ ] Verify proxy and auth header behavior remains intact.

### 15.3 CI Pipeline Checklist
- [ ] Remove stale CI steps that target removed assets.
- [ ] Preserve critical checks and guardrails.
- [ ] Keep job intent clear and non-duplicative.
- [ ] Ensure changed scripts are executable and referenced correctly.

### 15.4 Runtime API Path Checklist
- [ ] Direct API path auth behavior validated.
- [ ] Web-proxy API path behavior validated.
- [ ] HTTPS front-door path validated.
- [ ] Error codes and payload expectations unchanged.

### 15.5 Archive/Session/Data Lifecycle Checklist
- [ ] Archive flow behavior unchanged or explicitly improved.
- [ ] Cleanup/prune cadence not accidentally altered.
- [ ] Active+archive read paths still coherent.
- [ ] Indexing assumptions unaffected by cleanup.

### 15.6 Documentation UX Checklist
- [ ] New contributor can identify setup path in <5 min.
- [ ] Runtime verification path is explicit and short.
- [ ] Troubleshooting section maps to actual common failures.
- [ ] Historical audits are clearly marked as historical.

---

## 16) Reporting Formats

### 16.1 Standup Format

```md
## Standup [timestamp]
- Completed:
- In progress:
- Next:
- Risks/blockers:
- Decisions made:
```

### 16.2 Wave Summary Format

```md
## Wave [N] Summary
- Scope:
- Changes made:
- Validation run:
- Failures encountered:
- Fixes applied:
- Final status:
- Residual risk:
```

### 16.3 Final Executive Summary Format

```md
## Executive Summary
- Objective:
- Total files reviewed:
- Total deletions/refactors/docs updates:
- Runtime status:
- CI/test status:
- Deferred items:
- GO/NO-GO:
- Top residual risks:
```

---

## 17) Optional Add-ons (when you want maximum rigor)

### Add-on A — Two-Pass Approval
- Pass 1: Inventory + planned actions only.
- Pass 2: Execute only pre-approved actions.

### Add-on B — Rollback Ledger
- For each medium/high risk story, write explicit rollback steps.

### Add-on C — Delta Metrics
Track before/after:
- script count
- doc count
- duplicate module count
- failing check count
- unresolved TODO/FIXME count (if tracked)

---

## 18) Ready-to-Paste “Ultra Long” Super Prompt

```md
You are now the PO+Principal Engineer+Release Manager for a high-discipline repository cleanup/refactor sprint.

You must deliver measurable cleanup outcomes with runtime safety and full auditability.

### Non-Negotiable Exclusions
- aria_memories/**
- aria_souvenirs/**
No modifications under these paths.

### Primary Outcomes
1. Remove dead/obsolete files/scripts/docs with evidence.
2. Consolidate duplicate patterns and reduce complexity.
3. Preserve critical runtime behavior unless explicit migration is documented.
4. Improve documentation coherence and onboarding clarity.
5. Produce final GO/NO-GO with evidence-backed reasoning.

### Required Files
- tasks/repo_cleanup_plan.md
- tasks/repo_cleanup_inventory.md
- tasks/repo_cleanup_decisions.md
- tasks/repo_cleanup_validation.md
- tasks/repo_cleanup_risk_register.md
- tasks/repo_cleanup_final_report.md

### Mandatory Execution
Phase A: Census
- Enumerate major code/runtime domains.
- Enumerate scripts and classify usage status.
- Enumerate docs by topic and truth-source confidence.
- Enumerate tests/checks and critical path protection.
- Build KEEP/REFACTOR/DELETE/DEFER matrix.

Phase B: Prioritize
- Rank by runtime risk reduction first, then maintenance burden reduction.
- Build wave plan with explicit validation gates.

Phase C: Wave 1 Safe Prune
- Execute only high-confidence deletions and retirements.
- For each deletion, verify references and record rationale.
- Run targeted validation and log result.
- Repair regressions immediately, then revalidate.

Phase D: Wave 2 Structural Refactor
- Consolidate duplicate logic and simplify low-risk structure.
- Keep contract behavior stable unless migration notes are written.
- Validate touched and dependent surfaces.
- Log all decisions and risks.

Phase E: Wave 3 Stability
- Run smoke and key integration checks.
- Investigate failures to root cause.
- Apply smallest complete fix.
- Re-run until stable and document results.

Phase F: Wave 4 Documentation Truth-Sync
- Choose canonical docs per topic.
- Merge unique value from duplicates.
- Retire outdated docs with clear status labeling.
- Ensure setup/run/verify instructions reflect reality.

Phase G: Final Acceptance
- Execute final checklist and produce GO/NO-GO.
- Summarize removed/refactored/deferred with rationale.
- Publish residual risks and follow-up backlog.

### Hard Rules
- No speculative rewrites.
- No mass deletions without per-item evidence.
- No hidden contract changes.
- No unverified pass claims.
- If uncertain: DEFER and document.

### Validation Discipline
- Start with narrow checks closest to changes.
- Expand to broader checks as confidence grows.
- Capture command, output summary, failure cause, fix, and rerun result.

### Story-Level Definition of Done
A story is done only when:
- objective and rationale are explicit,
- changes are implemented,
- validation evidence exists,
- docs are updated if behavior changed,
- no unresolved regression remains in touched surface,
- exclusion constraint remained intact.

### Reporting Expectations
At each major batch provide standup:
- completed
- in progress
- next
- risks/blockers
- decisions

Final report must include:
- executive summary
- per-epic outcomes
- detailed removals/refactors
- validation summary
- deferred backlog
- residual risks
- GO/NO-GO with explicit rationale

Begin immediately with:
1) inventory scaffold,
2) top-priority wave plan,
3) first safe-prune proposal,
then execute.
```

---

## 19) Notes for Your Repo Context (optional preface)

You can prepend this tiny context block when starting a session:

```md
Repository context notes:
- Keep runtime/API/web path integrity first.
- Preserve guardrail and smoke capabilities.
- Favor deterministic scripts and clear docs.
- Focus cleanup on high-noise areas first.
- Exclude aria_memories/** and aria_souvenirs/**.
```

---

## 20) Final Usage Guidance

- Use **Strict mode** for production confidence.
- Use **Aggressive mode** for broad prune when confidence is high.
- Use **Conservative mode** when stability risk is elevated.
- Keep all work evidence-first and exclusion-safe.

This V2 is designed to be expanded further into an even larger pack (e.g., per-subsystem prompts) if needed.
