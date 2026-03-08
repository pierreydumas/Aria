# Aria — PO Documentation-vs-Implementation Gap Analysis Mega Prompt (50k-Scale, Multi-Mode)

> **Purpose**: This is a long-form, high-control prompt pack for autonomous documentation-vs-implementation gap analysis sprints.
> Use this when you want the agent to run like a Product Owner + Technical Writer + Principal Engineer + QA Lead with strict evidence gates — auditing every claim documentation makes against what the codebase actually does, finding undocumented features, identifying documented-but-missing implementations, and producing actionable improvement plans.

---

## 0) Quick Start

Copy one of the variant prompts from Section 4 into your coding agent and run it against this repository.

### Hard Exclusion (always)
- `aria_memories/**`
- `aria_souvenirs/**`

No change of any kind is allowed under excluded paths. They may be read for context if needed.

### If you only use one block
Use **Section 4.1 (Strict Gap Analysis Mode)**.

### Context Priming (paste before any variant)
```md
Repository: Aria Blue v3.0.0 — Autonomous AI Agent Platform
Stack: Python 3.13, FastAPI, Flask, SQLAlchemy 2.0 async, PostgreSQL 16, Docker Compose, LiteLLM, MLX
Packages: aria_engine (orchestration), aria_agents (agent pool), aria_skills (43 active skills), aria_models (LLM routing), aria_mind (consciousness/soul)
API: FastAPI at src/api/ — 36 router files, 240+ REST endpoints, 2 WebSocket, 1 GraphQL
Dashboard: Flask + Chart.js at src/web/ — run `ls src/web/templates/ | wc -l` for current count
Docker: stacks/brain/docker-compose.yml — 10+ services (db, api, web, engine, litellm, traefik, browser, tor, sandbox, monitoring)
Tests: pytest — architecture compliance, unit, integration, E2E, load
CI: GitHub Actions — .github/workflows/test.yml, tests.yml
```

---

## 1) Objective Contract

You are responsible for an end-to-end documentation-vs-implementation gap analysis sprint with production-safe behavior. This is a **read-heavy, write-precise** sprint: you read extensively, verify exhaustively, and write targeted corrections.

### Primary Goals
1. **Discover documentation lies** — statements in docs that do not match what the code actually does.
2. **Discover silent features** — implemented functionality that has no documentation anywhere.
3. **Discover phantom features** — documented functionality that does not exist in the codebase.
4. **Discover drift** — docs that were once accurate but have fallen behind code evolution.
5. **Discover configuration mismatches** — documented config/env vars that differ from actual usage.
6. **Quantify coverage** — produce a documentation coverage score per domain.
7. **Produce improvement plan** — prioritized, actionable corrections with effort estimates.
8. **Execute approved fixes** — apply documentation corrections with validation evidence.

### Non-Goals
- No speculative code rewrites to match docs (docs adapt to code, not the reverse, unless the code is clearly buggy).
- No architecture "big bang" changes.
- No cosmetic doc formatting without substantive accuracy improvement.
- No touching excluded folders.
- No inventing features that don't exist to fill doc gaps.

### Core Principle
> **Code is the source of truth.** When documentation disagrees with working code, the documentation is wrong — unless the code is clearly a bug, in which case file it as a bug finding.

---

## 2) Global Rules (applies to all modes)

1. **Read before judging**: verify every doc claim against actual source code, not assumptions.
2. **Cite evidence**: every gap finding must include file paths, line numbers, and code snippets.
3. **Classify precisely**: use the gap taxonomy (Section 6) for every finding.
4. **Prioritize by impact**: user-facing and onboarding-critical gaps rank highest.
5. **Batch fixes safely**: smallest coherent batch per change-set.
6. **Validate each fix**: ensure no new contradictions are introduced.
7. **Do not hide uncertainty**: mark confidence levels on every finding.
8. **No fake pass claims**: report exact verification outcomes.
9. **No edits in excluded folders** under any condition.
10. **Preserve existing doc value**: when correcting, keep useful context — don't strip docs to skeleton.

---

## 3) Required Artifacts

Create and maintain these files during execution:

- `tasks/gap_analysis_plan.md`
- `tasks/gap_analysis_inventory.md`
- `tasks/gap_analysis_findings.md`
- `tasks/gap_analysis_coverage.md`
- `tasks/gap_analysis_fixes.md`
- `tasks/gap_analysis_risk_register.md`
- `tasks/gap_analysis_final_report.md`

If files already exist, update rather than duplicate.

### Artifact Minimum Schema

#### `gap_analysis_plan.md`
```md
# Gap Analysis Sprint Plan

## Objective
[What this sprint will audit and deliver]

## Scope
[Which documentation files and code domains are in scope]

## Phases
[Phase breakdown with acceptance criteria]

## Timeline
[Phase sequencing and dependencies]

## Exclusions
[What is explicitly out of scope and why]

## Success Criteria
[Measurable criteria for sprint completion]
```

#### `gap_analysis_inventory.md`
```md
# Documentation Inventory

| Doc File | Domain | Last Updated | Lines | Source-of-Truth Level | Code Counterpart | Status |
|----------|--------|--------------|-------|----------------------|------------------|--------|
| README.md | Overview | ... | ... | Primary | Multiple | AUDITED / PENDING |
| ARCHITECTURE.md | Design | ... | ... | Primary | aria_engine/, aria_skills/ | AUDITED / PENDING |
```

Columns:
- **Doc File**: path to the documentation file
- **Domain**: what area it covers (API, deployment, skills, architecture, etc.)
- **Last Updated**: last meaningful edit date (from git blame or content dating)
- **Lines**: line count
- **Source-of-Truth Level**: Primary (canonical), Secondary (supplementary), Tertiary (historical/reference)
- **Code Counterpart**: which code modules/files this doc describes
- **Status**: PENDING / IN-PROGRESS / AUDITED / SKIPPED

#### `gap_analysis_findings.md`
```md
# Gap Analysis Findings

## Finding [GAP-001]: [Title]

- **Type**: LIE | PHANTOM | SILENT | DRIFT | CONFIG_MISMATCH | INCOMPLETE | STALE_EXAMPLE
- **Severity**: CRITICAL | HIGH | MEDIUM | LOW | INFO
- **Confidence**: HIGH | MEDIUM | LOW
- **Doc File**: [path to documentation file]
- **Doc Line(s)**: [line numbers of the incorrect/missing content]
- **Doc Claim**: [what the documentation says]
- **Code Reality**: [what the code actually does]
- **Code File(s)**: [path(s) to relevant source files]
- **Code Line(s)**: [line numbers showing the reality]
- **Impact**: [who is affected and how — onboarding, operations, debugging, etc.]
- **Suggested Fix**: [specific correction to make]
- **Fix Effort**: XS | S | M | L | XL
- **Status**: FOUND | CONFIRMED | FIXED | DEFERRED | WONT_FIX
```

#### `gap_analysis_coverage.md`
```md
# Documentation Coverage Matrix

## Overall Score: [X]% documented, [Y]% accurate

| Domain | Total Features | Documented | Accurate | Coverage % | Accuracy % | Grade |
|--------|---------------|------------|----------|------------|------------|-------|
| API Endpoints | 222 | ... | ... | ...% | ...% | A/B/C/D/F |
| Skills | 40+ | ... | ... | ...% | ...% | A/B/C/D/F |
| Configuration | ... | ... | ... | ...% | ...% | A/B/C/D/F |
| Docker Services | 10+ | ... | ... | ...% | ...% | A/B/C/D/F |
| CLI Commands | ... | ... | ... | ...% | ...% | A/B/C/D/F |
| Database Schema | 37 models | ... | ... | ...% | ...% | A/B/C/D/F |

### Grading Scale
- A: >90% coverage AND >95% accuracy
- B: >75% coverage AND >85% accuracy
- C: >60% coverage AND >75% accuracy
- D: >40% coverage AND >60% accuracy
- F: Below 40% coverage OR below 60% accuracy
```

#### `gap_analysis_fixes.md`
```md
# Gap Analysis Fixes Applied

## Fix [FIX-001]: [Title]

- **Finding**: GAP-XXX
- **File Modified**: [path]
- **Change Summary**: [what was changed]
- **Before**: [old text snippet]
- **After**: [new text snippet]
- **Validation**: [how correctness was verified]
- **Status**: APPLIED | REVERTED | PENDING_REVIEW
```

#### `gap_analysis_risk_register.md`
```md
# Gap Analysis Risk Register

| Risk ID | Description | Trigger | Likelihood | Impact | Mitigation | Residual Risk |
|---------|-------------|---------|------------|--------|------------|---------------|
| RISK-001 | ... | ... | Low/Med/High | Low/Med/High | ... | ... |
```

#### `gap_analysis_final_report.md`
```md
# Gap Analysis Final Report

## Executive Summary
[High-level findings, coverage scores, and recommendation]

## Sprint Metrics
- Total docs audited: X
- Total findings: X (Critical: X, High: X, Medium: X, Low: X)
- Total fixes applied: X
- Coverage score before: X%
- Coverage score after: X%
- Accuracy score before: X%
- Accuracy score after: X%

## Findings by Domain
[Grouped findings summary per domain]

## Fixes Applied
[Summary of all corrections made]

## Deferred Items
[Items intentionally left for follow-up]

## Residual Risk
[Remaining documentation risk areas]

## Recommendations
[Prioritized improvement recommendations]

## GO / NO-GO
[Explicit verdict with rationale]
```

---

## 4) Prompt Variants

Use one variant at a time.

---

### 4.1 Strict Gap Analysis Mode (default)

```md
You are operating as Product Owner + Technical Writer + Principal Engineer + QA Lead.

Mission:
Perform a full documentation-vs-implementation gap analysis sprint with strict evidence-based verification, comprehensive coverage scoring, and production-safe documentation corrections.

Hard exclusions (do not modify, read-only for context if needed):
- aria_memories/**
- aria_souvenirs/**

Deliverables to create/maintain:
- tasks/gap_analysis_plan.md
- tasks/gap_analysis_inventory.md
- tasks/gap_analysis_findings.md
- tasks/gap_analysis_coverage.md
- tasks/gap_analysis_fixes.md
- tasks/gap_analysis_risk_register.md
- tasks/gap_analysis_final_report.md

Source-of-truth hierarchy (highest to lowest):
1. Running code behavior (imports, class definitions, route registrations)
2. Configuration files (docker-compose.yml, models.yaml, skill.json, pyproject.toml)
3. Test assertions (what tests expect = implicit contract)
4. Primary documentation (README.md, ARCHITECTURE.md, DEPLOYMENT.md, SKILLS.md, MODELS.md, API.md)
5. Secondary documentation (docs/*.md, aria_skills/*/SKILL.md, inline docstrings)

Core Principle:
When documentation disagrees with working code, the documentation is wrong — unless the code is clearly a bug.

Execution protocol:
1) Build complete documentation inventory with source-of-truth classification.
2) Audit each documentation domain against its code counterpart:
   - Phase 1: Architecture & Design docs vs actual code structure
   - Phase 2: API & Endpoint docs vs actual route registrations and handlers
   - Phase 3: Skill docs vs actual skill implementations and manifests
   - Phase 4: Deployment & Config docs vs actual Docker/compose/env setup
   - Phase 5: Model routing docs vs actual model configuration and code
   - Phase 6: Dashboard/Web docs vs actual templates and Flask routes
   - Phase 7: Database & ORM docs vs actual models and migrations
   - Phase 8: Testing & CI docs vs actual test files and workflows
3) For each finding, cite exact file paths, line numbers, and code evidence.
4) Score documentation coverage and accuracy per domain.
5) Prioritize findings by impact: onboarding-critical > operations-critical > reference.
6) Apply approved fixes in batches, validating after each batch.
7) Produce final report with GO/NO-GO on documentation quality.

Rules:
- No finding without code evidence.
- No fix without verification that the new text matches code reality.
- No cosmetic-only changes — every edit must improve accuracy.
- If uncertain about code behavior: test it, don't guess.
- Every finding must have a severity, confidence, and suggested fix.
- Every fix must show before/after and validation method.

Acceptance gate for each finding:
- Gap type is classified correctly
- Evidence is specific (file + line, not just "somewhere in...")
- Impact assessment is realistic
- Suggested fix is concrete and actionable
- Confidence level is honest

Start immediately with a documentation inventory and initial audit plan.
```

---

### 4.2 Aggressive Coverage Mode (breadth-first, fast scan)

```md
You are operating as Product Owner + Technical Writer under aggressive coverage mode.

Goal:
Maximize the breadth of documentation-vs-code verification quickly. Identify the highest-impact gaps across all domains before deep-diving into any single area.

Hard exclusions:
- aria_memories/**
- aria_souvenirs/**

Required outputs:
- tasks/gap_analysis_plan.md
- tasks/gap_analysis_inventory.md
- tasks/gap_analysis_findings.md
- tasks/gap_analysis_coverage.md
- tasks/gap_analysis_final_report.md

Strategy:
- Scan all docs rapidly, marking obvious gaps first.
- Use automated checks where possible (grep for dead links, count endpoints vs docs, compare skill.json vs SKILL.md).
- Front-load high-impact areas: README accuracy, DEPLOYMENT correctness, API endpoint coverage.
- Batch findings by domain, then prioritize.
- Apply quick fixes for clear-cut cases; defer ambiguous ones.

Guardrails:
- No finding without at least one code reference.
- No fix that introduces new inaccuracies.
- Breadth over depth — cover all domains before going deep on any.
- Time-box each domain scan to avoid rabbit-holing.

Working rhythm:
- Inventory → scan all domains → rank findings → fix highest-impact → document → score → report.
- If a domain is clean: note it and move on.

Completion criteria:
- All major doc files inventoried and scanned.
- Coverage matrix populated for all domains.
- Top 20 highest-impact findings documented with evidence.
- Quick fixes applied where safe.
- Final report includes coverage scores and priority backlog.

Begin now with a rapid documentation inventory and domain-by-domain scan plan.
```

---

### 4.3 Deep Audit Mode (depth-first, maximum rigor)

```md
You are operating as Product Owner + Technical Writer + QA Lead in deep audit mode.

Goal:
Perform exhaustive, line-by-line verification of documentation claims against code reality. Prioritize accuracy and completeness over speed.

Hard exclusions:
- aria_memories/**
- aria_souvenirs/**

Required outputs:
- tasks/gap_analysis_plan.md
- tasks/gap_analysis_inventory.md
- tasks/gap_analysis_findings.md
- tasks/gap_analysis_coverage.md
- tasks/gap_analysis_fixes.md
- tasks/gap_analysis_risk_register.md
- tasks/gap_analysis_final_report.md

Approach:
- Audit one documentation domain at a time, exhaustively.
- For each doc section: read the claim, locate the code, verify or falsify.
- For each code module: check if adequate documentation exists.
- Build bidirectional coverage map: doc→code AND code→doc.
- Cross-reference multiple docs for contradictions.
- Verify code examples in docs actually work or are syntactically valid.

Hard stop rules:
- If a doc area has >10 unresolved findings, pause and fix before continuing.
- If automation is possible (e.g., endpoint counting), use it before manual review.
- If a finding contradicts a source-of-truth file: escalate severity.

Completion criteria:
- Every primary documentation file audited line-by-line.
- Bidirectional coverage map complete.
- All CRITICAL and HIGH findings addressed.
- Accuracy score >90% for primary docs after fixes.
- Comprehensive final report with metrics and recommendations.

Start with the highest-impact documentation file and audit it exhaustively before moving to the next.
```

---

### 4.4 Improvement-Focused Mode (gap analysis → enhancement plan)

```md
You are operating as Product Owner + Technical Writer in improvement-focused mode.

Goal:
Use gap analysis as a foundation to produce a comprehensive documentation improvement roadmap. Beyond finding gaps, propose new documentation, restructured navigation, improved examples, and better onboarding paths.

Hard exclusions:
- aria_memories/**
- aria_souvenirs/**

Required outputs:
- tasks/gap_analysis_plan.md
- tasks/gap_analysis_inventory.md
- tasks/gap_analysis_findings.md
- tasks/gap_analysis_coverage.md
- tasks/gap_analysis_fixes.md
- tasks/gap_analysis_final_report.md
- tasks/doc_improvement_roadmap.md (ADDITIONAL)

Strategy:
- Perform standard gap analysis across all domains.
- For each domain, evaluate not just accuracy but completeness, clarity, and usability.
- Identify onboarding friction points — where would a new developer get stuck?
- Identify operational friction points — where would a DevOps person misunderstand deployment?
- Propose new documentation where needed (architecture decision records, troubleshooting guides, etc.).
- Propose restructuring where doc navigation is confusing.
- Estimate effort for each improvement.

Improvement categories:
1. **Accuracy fixes** — correct wrong information
2. **Completeness additions** — document undocumented features
3. **Clarity improvements** — rewrite confusing sections
4. **Example updates** — fix or add code examples
5. **Navigation improvements** — better cross-linking, table of contents
6. **New documents** — entirely new docs for undocumented areas
7. **Deprecation notices** — mark outdated content clearly

Working rhythm:
- Audit → find gaps → categorize improvements → estimate effort → prioritize → roadmap → execute quick wins → document.

Completion criteria:
- Gap analysis complete with coverage scores.
- Improvement roadmap with prioritized items and effort estimates.
- Quick wins (XS/S effort) applied.
- Roadmap published for future sprints.
- Final report includes before/after coverage comparison.

Begin with gap analysis, then pivot to improvement planning after findings stabilize.
```

---

## 5) Expanded Checklist Library

Use these as copyable checklists inside your sprint docs.

---

### 5.1 Documentation Inventory Checklist

- [ ] Identify all markdown files at repository root.
- [ ] Identify all markdown files in docs/ directory.
- [ ] Identify all SKILL.md files in aria_skills/ subdirectories.
- [ ] Identify all README.md files in subpackages.
- [ ] Identify inline documentation in key source files (docstrings, module headers).
- [ ] Identify configuration documentation (.env.example, docker-compose comments).
- [ ] Identify generated documentation (API docs at /api/docs, GraphQL playground).
- [ ] Classify each doc as Primary / Secondary / Tertiary / Historical.
- [ ] Record line count, last-modified date, and code counterpart for each.
- [ ] Flag docs with no clear code counterpart.
- [ ] Flag code domains with no documentation.

---

### 5.2 Architecture Doc Audit Checklist

For ARCHITECTURE.md and related design docs:

- [ ] Layer diagram matches actual package structure.
- [ ] Layer numbering (L0-L4) matches skill.json declarations.
- [ ] Data flow description matches actual import chains.
- [ ] Service list matches docker-compose.yml services.
- [ ] Database schema description matches src/api/db/models.py.
- [ ] Memory architecture description matches aria_mind/memory.py implementation.
- [ ] Focus persona list matches aria_mind/soul/focus.py.
- [ ] Agent role list matches aria_agents/base.py.
- [ ] CEO/orchestration pattern matches aria_agents/coordinator.py.
- [ ] Infrastructure diagram matches actual service topology.
- [ ] Cross-references to other docs are valid (no dead links).
- [ ] Version/date claims are current.

---

### 5.3 API Documentation Audit Checklist

For API.md, docs/API_ENDPOINT_INVENTORY.md, and related:

- [ ] Total endpoint count matches actual route registrations.
- [ ] Each documented route prefix exists in src/api/routers/.
- [ ] Each router file's endpoints are documented.
- [ ] HTTP methods (GET/POST/PUT/DELETE/PATCH) match route decorators.
- [ ] Request/response schemas match Pydantic models.
- [ ] Authentication requirements are correctly documented.
- [ ] WebSocket endpoints are documented.
- [ ] GraphQL schema description matches src/api/gql/ implementation.
- [ ] Security middleware features match src/api/security_middleware.py.
- [ ] Error response formats are accurately described.
- [ ] Rate limiting behavior matches implementation.
- [ ] Documented parameter names match actual parameter names.
- [ ] Example request/response payloads are valid.
- [ ] Deprecated endpoints are marked as such.
- [ ] Undocumented endpoints are identified and cataloged.

---

### 5.4 Skill Documentation Audit Checklist

For SKILLS.md, aria_skills/SKILL_STANDARD.md, aria_skills/SKILL_CREATION_GUIDE.md, and per-skill SKILL.md:

- [ ] Skill count in docs matches actual aria_skills/ subdirectories.
- [ ] Each skill's layer in docs matches its skill.json "layer" field.
- [ ] Skill hierarchy rules match tests/check_architecture.py enforcement.
- [ ] BaseSkill interface description matches aria_skills/base.py.
- [ ] SkillRegistry description matches aria_skills/registry.py.
- [ ] SkillResult/SkillConfig/SkillStatus match base.py definitions.
- [ ] Template description matches aria_skills/_template/ contents.
- [ ] Each skill with SKILL.md has accurate tool descriptions.
- [ ] Each skill's dependencies in docs match skill.json "dependencies".
- [ ] Pipeline system description matches pipeline.py and pipeline_executor.py.
- [ ] Latency tracking description matches latency.py.
- [ ] Skills without SKILL.md are identified.
- [ ] Documented skills that don't exist in code are identified.

---

### 5.5 Deployment Documentation Audit Checklist

For DEPLOYMENT.md and ROLLBACK.md:

- [ ] Prerequisites list is complete and versions are correct.
- [ ] Quick deploy commands actually work.
- [ ] Docker Compose service list matches actual compose file.
- [ ] Environment variable list matches .env.example and actual code usage.
- [ ] Port numbers match docker-compose.yml port mappings.
- [ ] Service URLs are correct (localhost vs host IP).
- [ ] Health check commands return expected results.
- [ ] MLX server setup instructions are accurate for current model.
- [ ] API key setup instructions are current.
- [ ] Database architecture description matches actual schemas.
- [ ] Init scripts description matches stacks/brain/init-scripts/.
- [ ] Rollback procedures are tested and valid.
- [ ] Monitoring URLs (Prometheus, Grafana) are correct.
- [ ] SSH/connection details are current.
- [ ] First-run script behavior matches description.

---

### 5.6 Model Routing Documentation Audit Checklist

For MODELS.md and aria_models/README.md:

- [ ] Tier priority description matches actual routing logic.
- [ ] Model list matches aria_models/models.yaml entries.
- [ ] Provider configuration matches LiteLLM proxy setup.
- [ ] Fallback chain description matches actual failover behavior.
- [ ] Context window sizes match model specs.
- [ ] Focus-to-model mapping matches aria_mind/soul/focus.py.
- [ ] LiteLLM config generation script works as documented.
- [ ] Benchmark script works as documented.
- [ ] Cost tracking description matches implementation.
- [ ] Free model list is current (models may have changed tiers).

---

### 5.7 Dashboard Documentation Audit Checklist

For API.md (dashboard section) and src/web/:

- [ ] Template count matches actual src/web/templates/ file count.
- [ ] Listed pages match actual template files.
- [ ] Page features described match template content and JavaScript.
- [ ] Chart types mentioned match Chart.js implementations.
- [ ] API proxy behavior description matches Flask app configuration.
- [ ] Static asset references are valid.
- [ ] Template names match Flask route registrations.
- [ ] Dashboard URL paths match actual registered routes.
- [ ] Auto-refresh behavior is accurately described.
- [ ] Undocumented dashboard pages are identified.

---

### 5.8 Database Documentation Audit Checklist

For API.md (database section), ARCHITECTURE.md (memory/persistence), src/api/db/MODELS.md:

- [ ] ORM model count matches actual models in src/api/db/models.py.
- [ ] Schema names (aria_data, aria_engine) match model annotations.
- [ ] Table names listed match actual class __tablename__ attributes.
- [ ] Relationship descriptions match SQLAlchemy relationship() definitions.
- [ ] Column types described match actual Column() definitions.
- [ ] Index descriptions match actual Index() definitions.
- [ ] Migration strategy description matches alembic/ configuration.
- [ ] Dual-database architecture (aria_warehouse + litellm) matches reality.
- [ ] Seed data description matches init scripts.
- [ ] "No raw SQL" claim is verified (grep for text(), execute()).

---

### 5.9 Testing Documentation Audit Checklist

For README.md (testing section), CONTRIBUTING.md (testing section), CI workflow files:

- [ ] Test commands documented actually work.
- [ ] Test file organization matches documented structure.
- [ ] CI workflow steps match documented CI process.
- [ ] Coverage commands match actual pytest configuration.
- [ ] Architecture test description matches tests/test_architecture.py behavior.
- [ ] Load test commands match actual test scripts.
- [ ] Memory profiling commands match actual profiling scripts.
- [ ] Test markers and categories are accurately described.
- [ ] Required environment for tests is documented.

---

### 5.10 Configuration Documentation Audit Checklist

- [ ] Every env var in .env.example is documented somewhere.
- [ ] Every env var referenced in code is present in .env.example.
- [ ] Default values documented match actual defaults in code.
- [ ] Config file paths documented match actual file locations.
- [ ] Docker Compose volume mounts match documented paths.
- [ ] Service dependencies documented match depends_on in compose.
- [ ] Health check configurations match documented behavior.
- [ ] Network configuration matches documented topology.

---

### 5.11 Cross-Reference Integrity Checklist

- [ ] All markdown links resolve to existing files.
- [ ] All "See also" / "Related" sections have valid targets.
- [ ] No circular references create confusion.
- [ ] Source-of-truth references point to actual canonical files.
- [ ] Version numbers are consistent across docs.
- [ ] Date references are consistent and current.
- [ ] Service names are consistent across docs, compose, and code.
- [ ] Package names are consistent across docs and pyproject.toml.

---

### 5.12 README Quality Checklist

- [ ] Project description accurately reflects current capabilities.
- [ ] Tech stack table matches actual dependencies.
- [ ] Quick start instructions actually work end-to-end.
- [ ] Documentation table lists all primary docs.
- [ ] Source-of-truth table lists all canonical files.
- [ ] License section is accurate.
- [ ] Badges reflect current state.
- [ ] No dead links.
- [ ] No references to removed/renamed files.

---

## 6) Gap Taxonomy

Every finding MUST be classified using exactly one of these types:

### 6.1 LIE
**Documentation makes a factual claim that is provably false.**

Example: "API has 180 endpoints" when code shows 222.
Evidence required: doc quote + code count.

### 6.2 PHANTOM
**Documentation describes a feature, endpoint, command, or file that does not exist in the codebase.**

Example: DEPLOYMENT.md references `scripts/health_check.sh` but the file doesn't exist.
Evidence required: doc quote + file/grep search showing absence.

### 6.3 SILENT
**Code implements functionality that has zero documentation anywhere.**

Example: A full RPG campaign system exists in aria_skills/rpg/ with no mention in any doc.
Evidence required: code showing the feature + grep showing no doc mentions.

### 6.4 DRIFT
**Documentation was once accurate but code has evolved past it.**

Example: ARCHITECTURE.md shows 5 focus personas but code now has 7.
Evidence required: doc claim + code showing current state + git evidence of change.

### 6.5 CONFIG_MISMATCH
**Documented configuration doesn't match actual environment variables, defaults, or settings.**

Example: .env.example lists `DB_HOST=localhost` but docker-compose uses `aria-db`.
Evidence required: doc/config value + actual usage in code/compose.

### 6.6 INCOMPLETE
**Documentation covers a topic but misses significant aspects of the implementation.**

Example: SKILLS.md describes the 5-layer hierarchy but doesn't mention the pipeline system.
Evidence required: what doc covers + what code has that doc doesn't mention.

### 6.7 STALE_EXAMPLE
**Code examples, commands, or snippets in documentation are outdated or non-functional.**

Example: README shows `python -m aria_mind --start` but the actual CLI flag is `--run`.
Evidence required: doc command + actual working command from code.

### 6.8 CONTRADICTION
**Two or more documentation files make conflicting claims about the same thing.**

Example: README says "43 templates" but API.md says "40 templates".
Evidence required: both doc quotes + actual code count.

### 6.9 DEAD_LINK
**Documentation contains a hyperlink to a file, URL, or anchor that doesn't exist.**

Example: `[AUDIT_REPORT.md](AUDIT_REPORT.md)` but AUDIT_REPORT.md was deleted.
Evidence required: the link + proof target doesn't exist.

### 6.10 MISLEADING
**Documentation is technically true but creates a wrong impression of how things work.**

Example: "LiteLLM handles all routing" — technically true but misses that aria_engine also does model selection.
Evidence required: doc claim + code showing the fuller picture.

---

## 7) Severity Classification Rules

### CRITICAL
- Prevents a new developer from setting up the project.
- Causes data loss or security misconfiguration if followed.
- Contradicts a safety or security mechanism.
- References a completely nonexistent critical-path feature.

### HIGH
- Causes failed deployment or operations if followed literally.
- Significant feature misrepresentation.
- Missing documentation for security-sensitive functionality.
- Configuration mismatches that cause service failures.

### MEDIUM
- Moderate confusion for developers or operators.
- Outdated counts, versions, or minor factual errors.
- Missing documentation for non-critical features.
- Stale examples that are close but not quite right.

### LOW
- Minor cosmetic inaccuracies.
- Documentation that's slightly outdated but still mostly useful.
- Missing docs for internal-only or rarely-used features.
- Formatting issues that don't affect comprehension.

### INFO
- Observations about documentation quality or structure.
- Suggestions for improvement that aren't fixing errors.
- Notes about documentation best practices.

---

## 8) Autonomous Execution Rubric (step-by-step)

Use this as strict operating instructions for autonomous agents.

### Step 1 — Initialize
1. Create/update required task artifacts.
2. Write mission statement and hard exclusions at top of plan.
3. Declare selected mode (Strict/Aggressive/Deep/Improvement).
4. Declare what documentation and code domains will be audited.
5. List assumptions and current unknowns.

### Step 2 — Documentation Inventory
6. Enumerate all markdown files at repo root (*.md).
7. Enumerate all markdown files in docs/ directory.
8. Enumerate all SKILL.md files in aria_skills/ subdirectories.
9. Enumerate all README.md files in subpackages.
10. Enumerate inline documentation in key modules (docstrings).
11. Enumerate configuration documentation (.env.example, compose comments).
12. Classify each doc as Primary / Secondary / Tertiary / Historical.
13. Identify code counterpart for each doc.
14. Populate inventory table.

### Step 3 — Establish Code Baselines
15. Count actual API endpoints (router file analysis or endpoint matrix script).
16. Count actual skills (aria_skills/ subdirectories with __init__.py).
17. Count actual ORM models (src/api/db/models.py class count).
18. Count actual Docker services (docker-compose.yml service list).
19. Count actual dashboard templates (src/web/templates/ file count).
20. Count actual test files (tests/ file count).
21. Extract actual environment variables (grep os.environ/os.getenv across codebase).
22. Extract actual CLI commands (argparse/click definitions).
23. Record all baselines for comparison against doc claims.

### Step 4 — Phase 1: Architecture & Design Audit
24. Read ARCHITECTURE.md line by line.
25. Verify layer diagram against actual directory structure.
26. Verify skill hierarchy against skill.json files.
27. Verify data flow claims against import analysis.
28. Verify service topology against docker-compose.yml.
29. Verify memory architecture against aria_mind/memory.py.
30. Verify focus persona list against aria_mind/soul/focus.py.
31. Verify agent roles against aria_agents/base.py.
32. Log all findings with evidence.
33. Score architecture documentation coverage and accuracy.

### Step 5 — Phase 2: API & Endpoint Audit
34. Read API.md and docs/API_ENDPOINT_INVENTORY.md.
35. Compare documented endpoint count to actual endpoint count.
36. Verify each documented route prefix exists in routers.
37. Sample-check 20+ specific endpoints: method, path, handler, auth.
38. Verify GraphQL schema description against src/api/gql/.
39. Verify security middleware description against implementation.
40. Verify WebSocket endpoint documentation.
41. Identify undocumented endpoints.
42. Log all findings with evidence.
43. Score API documentation coverage and accuracy.

### Step 6 — Phase 3: Skill System Audit
44. Read SKILLS.md, SKILL_STANDARD.md, SKILL_CREATION_GUIDE.md.
45. Compare documented skill count to actual skill count.
46. Verify each skill's layer against its skill.json.
47. Verify BaseSkill/SkillRegistry descriptions against code.
48. Check which skills have SKILL.md and which don't.
49. Sample-check 10+ skill.json manifests for accuracy.
50. Verify skill template against _template/ directory.
51. Log all findings with evidence.
52. Score skill documentation coverage and accuracy.

### Step 7 — Phase 4: Deployment & Config Audit
53. Read DEPLOYMENT.md and ROLLBACK.md.
54. Verify every shell command in docs is valid (syntax check minimum).
55. Compare documented env vars against .env.example and code usage.
56. Verify Docker service list and ports against compose.
57. Verify health check URLs and expected responses.
58. Verify database architecture description against models and init scripts.
59. Verify MLX/model setup instructions.
60. Log all findings with evidence.
61. Score deployment documentation coverage and accuracy.

### Step 8 — Phase 5: Model Routing Audit
62. Read MODELS.md and aria_models/README.md.
63. Compare documented models against models.yaml.
64. Verify routing/failover description against code.
65. Verify focus-to-model mapping against soul/focus.py.
66. Verify LiteLLM configuration instructions.
67. Log all findings with evidence.
68. Score model documentation coverage and accuracy.

### Step 9 — Phase 6: Dashboard & Web Audit
69. Read API.md dashboard section.
70. Compare documented template count to actual file count.
71. Verify listed pages against actual template files.
72. Sample-check page features against template content.
73. Verify Flask route registrations match documented paths.
74. Identify undocumented dashboard pages.
75. Log all findings with evidence.
76. Score dashboard documentation coverage and accuracy.

### Step 10 — Phase 7: Database & ORM Audit
77. Read API.md database section and src/api/db/MODELS.md.
78. Compare documented model count to actual class count.
79. Verify schema names match model annotations.
80. Sample-check table/column descriptions against code.
81. Verify "no raw SQL" claim via grep.
82. Verify migration documentation against alembic/ setup.
83. Log all findings with evidence.
84. Score database documentation coverage and accuracy.

### Step 11 — Phase 8: Testing & CI Audit
85. Read test-related docs in README.md and CONTRIBUTING.md.
86. Verify test commands work or are syntactically valid.
87. Compare documented CI steps against .github/workflows/.
88. Verify architecture test description against test_architecture.py.
89. Log all findings with evidence.
90. Score testing documentation coverage and accuracy.

### Step 12 — Cross-Reference Integrity Scan
91. Check all markdown links across all audited docs.
92. Verify all "See also" / "Related" sections.
93. Check for contradictions between docs.
94. Check version consistency across docs.
95. Log all cross-reference findings.

### Step 13 — Build Coverage Matrix
96. Aggregate per-domain scores into coverage matrix.
97. Calculate overall documentation coverage percentage.
98. Calculate overall documentation accuracy percentage.
99. Assign letter grades per domain.
100. Identify the 3 best-documented and 3 worst-documented domains.

### Step 14 — Prioritize Findings
101. Sort findings by severity (CRITICAL first).
102. Within same severity, sort by impact (onboarding > operations > reference).
103. Within same impact, sort by fix effort (XS first).
104. Build prioritized fix plan.

### Step 15 — Execute Fixes (Phase A: Critical & High)
105. Fix all CRITICAL findings first.
106. Validate each fix doesn't introduce new inaccuracies.
107. Fix all HIGH findings next.
108. Validate each fix.
109. Log all fixes in fixes artifact.

### Step 16 — Execute Fixes (Phase B: Medium)
110. Fix MEDIUM findings that are XS or S effort.
111. Validate each fix.
112. Defer MEDIUM findings that are M+ effort with rationale.
113. Log all fixes and deferrals.

### Step 17 — Recalculate Coverage
114. Re-score all domains after fixes.
115. Calculate improvement delta.
116. Verify no new gaps were introduced.

### Step 18 — Final Acceptance
117. Run final cross-reference check.
118. Verify all CRITICAL and HIGH findings addressed.
119. Produce GO/NO-GO with rationale.
120. Publish final report with metrics, findings, fixes, and recommendations.

---

## 9) Source-of-Truth File Reference

These are the canonical code files that documentation must accurately describe. Use these as the primary verification targets.

### Configuration & Metadata
| File | What It Defines |
|------|----------------|
| `pyproject.toml` | Package name, version, dependencies, build config |
| `docker-compose.yml` | Root compose file (includes stacks/brain) |
| `stacks/brain/docker-compose.yml` | Full service definitions, ports, volumes, health checks |
| `stacks/brain/.env.example` | Required environment variables |
| `Makefile` | Development command shortcuts |
| `aria_models/models.yaml` | LLM model catalog, routing, tiers |
| `.github/workflows/test.yml` | CI pipeline definition |
| `.github/workflows/tests.yml` | Extended CI pipeline |

### Code Architecture
| File | What It Defines |
|------|----------------|
| `aria_skills/base.py` | BaseSkill, SkillConfig, SkillResult, SkillStatus |
| `aria_skills/registry.py` | SkillRegistry — auto-discovery, registration |
| `aria_skills/pipeline.py` | Pipeline definition engine |
| `aria_skills/pipeline_executor.py` | Pipeline execution runtime |
| `aria_skills/catalog.py` | Skill catalog generator CLI |
| `aria_skills/*/skill.json` | Per-skill manifest (layer, tools, deps) |
| `aria_agents/base.py` | Agent roles, base agent class |
| `aria_agents/coordinator.py` | Roundtable orchestration, multi-agent coordination |
| `aria_engine/entrypoint.py` | Engine boot sequence |
| `aria_engine/llm_gateway.py` | LLM gateway routing logic |
| `aria_engine/chat_engine.py` | Chat engine implementation |
| `aria_engine/roundtable.py` | Roundtable session management |
| `aria_engine/config.py` | Engine configuration |
| `aria_mind/soul/focus.py` | Focus personas definitions |
| `aria_mind/soul/identity.py` | Identity module |
| `aria_mind/soul/values.py` | Core values |
| `aria_mind/soul/boundaries.py` | Operational boundaries |
| `aria_mind/kernel/constitution.yaml` | Core constitution |
| `aria_mind/memory.py` | Memory management implementation |
| `aria_mind/cognition.py` | Cognitive functions |
| `aria_mind/metacognition.py` | Metacognitive functions |
| `aria_mind/heartbeat.py` | Heartbeat implementation |
| `aria_mind/security.py` | Security implementation |

### API & Database
| File | What It Defines |
|------|----------------|
| `src/api/routers/*.py` | All REST endpoint definitions |
| `src/api/gql/` | GraphQL schema and resolvers |
| `src/api/security_middleware.py` | Security middleware (rate limiting, injection detection) |
| `src/api/db/models.py` | All 37 ORM models |
| `src/api/db/session.py` | Database session management |
| `src/api/alembic/` | Database migration configuration |
| `stacks/brain/init-scripts/` | Database initialization scripts |

### Web Dashboard
| File | What It Defines |
|------|----------------|
| `src/web/app.py` | Flask application and routes |
| `src/web/templates/*.html` | Dashboard page templates |
| `src/web/static/` | Static assets (CSS, JS, images) |

### Scripts & Testing
| File | What It Defines |
|------|----------------|
| `tests/check_architecture.py` | Architecture enforcement rules |
| `scripts/generate_endpoint_matrix.py` | Endpoint inventory generator |
| `tests/e2e/runtime_smoke_check.py` | Runtime smoke tests |
| `tests/integration/guardrail_web_api_path.py` | Web/API path guardrails |
| `tests/test_architecture.py` | Architecture compliance tests |
| `tests/` | Full test suite |

---

## 10) Domain-Specific Verification Techniques

### 10.1 Counting Endpoints (Automated)
```bash
# Use existing script if available
python3 scripts/generate_endpoint_matrix.py

# Manual count
grep -rn "@router\.\(get\|post\|put\|delete\|patch\|websocket\)" src/api/routers/ | wc -l

# Per-router breakdown
for f in src/api/routers/*.py; do
  count=$(grep -c "@router\.\(get\|post\|put\|delete\|patch\|websocket\)" "$f" 2>/dev/null || echo 0)
  echo "$count $f"
done | sort -rn
```

### 10.2 Counting Skills
```bash
# Count skill directories (exclude _template and __pycache__)
ls -d aria_skills/*/ | grep -v _template | grep -v __pycache__ | wc -l

# List all skill.json files
find aria_skills -name "skill.json" -exec echo {} \;

# Extract layer info
find aria_skills -name "skill.json" -exec sh -c 'echo "$(dirname {}): $(cat {} | python3 -c "import sys,json; print(json.load(sys.stdin).get(\"layer\",\"?\"))")"' \;
```

### 10.3 Counting ORM Models
```bash
# Count SQLAlchemy model classes
grep -c "class.*Base)" src/api/db/models.py

# List model names
grep "class.*Base)" src/api/db/models.py | sed 's/class \(.*\)(Base).*/\1/'
```

### 10.4 Counting Docker Services
```bash
# From compose file
grep "^\s\+[a-z].*:" stacks/brain/docker-compose.yml | grep -v "#" | head -20
```

### 10.5 Counting Dashboard Templates
```bash
ls src/web/templates/*.html | wc -l
ls src/web/templates/*.html
```

### 10.6 Extracting Environment Variables from Code
```bash
# Find all env var references
grep -rn "os\.environ\|os\.getenv\|environ\.get" src/ aria_engine/ aria_skills/ aria_mind/ aria_agents/ | grep -v __pycache__

# Compare with .env.example
cat stacks/brain/.env.example
```

### 10.7 Checking Markdown Links
```bash
# Find all markdown links
grep -rn "\[.*\](.*\.md)" *.md docs/*.md

# Check if targets exist
grep -roh "\[.*\](\([^)]*\.md[^)]*\))" *.md docs/*.md | sed 's/.*(\(.*\))/\1/' | while read f; do
  [ ! -f "$f" ] && echo "DEAD: $f"
done
```

### 10.8 Verifying Architecture Rules
```bash
python3 tests/check_architecture.py
pytest tests/test_architecture.py -v
```

---

## 11) Verification Patterns (How to Prove Gaps)

### Pattern A: Count Verification
1. Find the documented claim: "API has X endpoints"
2. Count actual endpoints via code analysis or script
3. If different: finding type = LIE or DRIFT, depending on whether count was ever correct

### Pattern B: Existence Verification
1. Find a documented reference: "See scripts/health_check.sh"
2. Check if file exists: `ls scripts/health_check.sh`
3. If missing: finding type = PHANTOM or DEAD_LINK

### Pattern C: Behavior Verification
1. Find a documented behavior: "Skills auto-register via @SkillRegistry.register"
2. Check actual code for registration mechanism
3. If different: finding type = LIE or DRIFT

### Pattern D: Configuration Verification
1. Find a documented config: "Set DB_HOST in .env"
2. Check if code uses DB_HOST: `grep -r "DB_HOST" src/ aria_*/`
3. Check if .env.example includes it
4. If mismatch: finding type = CONFIG_MISMATCH

### Pattern E: Cross-Doc Verification
1. Find a claim in Doc A: "43 templates"
2. Find a claim in Doc B about same topic: "40 templates"
3. Verify against code: `ls src/web/templates/*.html | wc -l`
4. If docs disagree: finding type = CONTRADICTION

### Pattern F: Completeness Verification
1. List all code features in a domain (e.g., all skills)
2. Check which are mentioned in documentation
3. If features exist but aren't documented: finding type = SILENT
4. If documented but don't exist: finding type = PHANTOM

### Pattern G: Example Verification
1. Find a code example in docs
2. Check if the syntax is valid
3. Check if the imports exist
4. Check if the API/function signatures match current code
5. If outdated: finding type = STALE_EXAMPLE

---

## 12) Priority Matrix Templates

### 12.1 Finding Priority Matrix
```md
| Finding ID | Type | Severity | Impact Area | Fix Effort | Priority Score | Action |
|-----------|------|----------|-------------|------------|---------------|--------|
| GAP-001 | LIE | CRITICAL | Onboarding | XS | P1 | FIX NOW |
| GAP-002 | PHANTOM | HIGH | Operations | S | P1 | FIX NOW |
| GAP-003 | DRIFT | MEDIUM | Reference | M | P2 | FIX THIS SPRINT |
| GAP-004 | SILENT | LOW | Internal | L | P3 | BACKLOG |
```

### Priority Score Calculation
```
P1 (Fix Now)     = CRITICAL severity OR (HIGH severity + XS/S effort)
P2 (This Sprint) = HIGH severity + M effort OR MEDIUM severity + XS/S effort
P3 (Backlog)     = MEDIUM severity + M+ effort OR LOW severity
P4 (Won't Fix)   = INFO severity OR LOW impact + high effort
```

### 12.2 Domain Coverage Matrix
```md
| Domain | Docs | Code Features | Documented | Accurate | Missing Coverage | Grade |
|--------|------|---------------|------------|----------|-----------------|-------|
| API | API.md, INVENTORY.md | 222 endpoints | 200 | 185 | 22 undocumented | B |
| Skills | SKILLS.md | 40 skills | 35 | 30 | 5 undocumented | C |
| Deploy | DEPLOYMENT.md | 15 configs | 12 | 10 | 3 undocumented | B |
```

### 12.3 Fix Effort Matrix
```md
| Effort | Description | Typical Examples |
|--------|-------------|------------------|
| XS | <5 min, single number/name correction | Fix endpoint count, fix file name |
| S | 5-15 min, paragraph rewrite | Update feature description, fix example |
| M | 15-60 min, section rewrite | Rewrite deployment steps, update architecture diagram |
| L | 1-4 hours, multi-section or new doc | Write missing skill documentation, create new guide |
| XL | 4+ hours, major documentation effort | Create comprehensive API reference, restructure doc hierarchy |
```

---

## 13) Audit Execution Templates

### 13.1 Per-Doc Audit Template
```md
## Audit: [Document Name]

**File**: [path]
**Lines**: [count]
**Domain**: [what it covers]
**Code Counterpart**: [relevant code files]
**Audit Date**: [timestamp]

### Summary
- Claims verified: X
- Claims falsified: X
- Undocumented features found: X
- Coverage: X%
- Accuracy: X%

### Detailed Findings
[findings listed here]

### Recommendations
[specific improvements]
```

### 13.2 Per-Domain Audit Template
```md
## Domain Audit: [Domain Name]

**Docs Covering This Domain**: [list]
**Code Files in Domain**: [list]
**Audit Date**: [timestamp]

### Code Baseline
- Feature count: X
- Endpoint count: X (if applicable)
- Config items: X (if applicable)

### Documentation Baseline
- Total documented features: X
- Accuracy of documented features: X%

### Gap Summary
| Gap Type | Count | Severity Breakdown |
|----------|-------|--------------------|
| LIE | X | C:X H:X M:X L:X |
| PHANTOM | X | ... |
| SILENT | X | ... |
| DRIFT | X | ... |

### Detailed Findings
[findings listed here]

### Coverage Score
- Before fixes: X%
- After fixes: X%
```

---

## 14) Conservative vs Aggressive Decision Rules for Fixes

### Choose Aggressive fix only if all true
- The gap is clear-cut (HIGH confidence)
- The correct value is unambiguous from code
- The fix doesn't require domain expertise
- The doc section is clearly wrong, not ambiguous
- No risk of over-correction

### Force Conservative fix if any true
- The gap involves behavior that might be intentional
- Multiple interpretations of the code exist
- The fix requires understanding of deployment context not visible in code
- The documentation might reflect a planned future state
- The gap involves security-sensitive descriptions

### Defer if any true
- You can't determine the correct value from code alone
- The fix requires running the system to verify
- The documentation section serves a purpose beyond pure accuracy (e.g., aspiration, roadmap)
- Fixing would require restructuring multiple documents

---

## 15) Anti-Patterns to Explicitly Avoid

### During Audit
- Claiming a doc is "fine" without verifying claims against code.
- Using documentation to verify documentation (circular reasoning).
- Assuming code examples work without checking syntax/imports.
- Skipping sections because they "look right".
- Marking low confidence as high confidence.
- Over-counting findings by splitting one issue into many.
- Under-counting by combining multiple distinct issues.

### During Fixes
- Rewriting docs in your own style instead of minimal targeted corrections.
- Fixing cosmetic issues and calling it a gap fix.
- Adding speculative content not supported by code.
- Removing useful context while fixing inaccuracies.
- Breaking existing formatting or link structures.
- Fixing one doc without checking if the same claim appears in other docs.

### During Reporting
- Reporting coverage percentages without showing the math.
- Claiming improvement without before/after comparison.
- Hiding deferred items.
- Overstating the impact of fixes made.
- Understating residual risk.

---

## 16) GO / NO-GO Decision Rubric

### GO only if all are true
1. All primary documentation files have been audited.
2. Coverage matrix is populated for all major domains.
3. No CRITICAL findings remain unaddressed.
4. All HIGH findings are either fixed or deferred with explicit rationale.
5. Documentation accuracy score is >85% across primary docs.
6. Cross-reference integrity scan shows no dead links in primary docs.
7. Final report is complete with metrics, findings, and recommendations.

### NO-GO if any are true
1. Any CRITICAL finding remains unaddressed.
2. Coverage matrix is incomplete for major domains.
3. Documentation accuracy is <70% for any primary doc file.
4. Fixes introduced new contradictions.
5. Audit coverage is <60% of planned scope.

---

## 17) PO Command Phrases for Interactive Sessions

Use these commands in chat with your agent:

### Sprint Control
- `kickoff gap analysis strict`
- `kickoff gap analysis aggressive`
- `kickoff gap analysis deep`
- `kickoff gap analysis improvement`
- `show documentation inventory`
- `show coverage matrix`
- `show top 20 findings by severity`
- `show findings for [domain]`
- `show silent features`
- `show phantom features`
- `pause and present risks`

### Phase Control
- `execute phase 1 only` (architecture audit)
- `execute phase 2 only` (API audit)
- `execute phase 3 only` (skills audit)
- `skip to phase [N]`
- `deep audit [document name]`

### Fix Control
- `fix all critical findings`
- `fix all P1 findings`
- `fix [GAP-XXX]`
- `defer [GAP-XXX] because [reason]`
- `show fix log`
- `validate all fixes`

### Reporting
- `generate coverage report`
- `generate go/no-go report`
- `show improvement delta`
- `show deferred backlog`
- `create improvement roadmap`

---

## 18) Extended Execution Prompt (Full-Length, Direct Paste)

```md
You are the autonomous PO + Technical Writer + Principal Engineer + QA Lead for this documentation gap analysis sprint.

## Mission
Perform a comprehensive, evidence-based audit of all documentation against actual code implementation. Discover every gap, classify it, fix what you can, and produce a prioritized improvement plan for the rest.

## Hard Exclusions
Do not modify these paths under any condition:
- aria_memories/**
- aria_souvenirs/**

## Required Artifacts
Create/maintain:
- tasks/gap_analysis_plan.md
- tasks/gap_analysis_inventory.md
- tasks/gap_analysis_findings.md
- tasks/gap_analysis_coverage.md
- tasks/gap_analysis_fixes.md
- tasks/gap_analysis_risk_register.md
- tasks/gap_analysis_final_report.md

## Source of Truth Hierarchy
1. Running code (imports, classes, routes, configs)
2. Configuration files (compose, models.yaml, skill.json, pyproject.toml)
3. Test assertions (implicit contracts)
4. Primary documentation (README, ARCHITECTURE, DEPLOYMENT, SKILLS, MODELS, API)
5. Secondary documentation (docs/*.md, SKILL.md files, inline docstrings)

## Core Principle
Code is truth. When docs disagree with working code, docs are wrong — unless code is clearly a bug.

## Process

### Phase 0: Setup
1) Create all required artifacts.
2) Build documentation inventory table.
3) Establish code baselines (endpoint counts, skill counts, model counts, etc.).

### Phase 1: Architecture & Design Audit
4) Audit ARCHITECTURE.md against actual code structure.
5) Verify layer diagrams, data flows, service topology.
6) Verify memory architecture, focus personas, agent roles.
7) Score and log findings.

### Phase 2: API & Endpoint Audit
8) Audit API.md and docs/API_ENDPOINT_INVENTORY.md.
9) Compare documented vs actual endpoint counts and routes.
10) Sample-verify 20+ specific endpoints.
11) Identify undocumented endpoints.
12) Score and log findings.

### Phase 3: Skill System Audit
13) Audit SKILLS.md and skill creation docs.
14) Compare documented vs actual skill inventory.
15) Verify layer assignments and dependencies.
16) Check per-skill documentation coverage.
17) Score and log findings.

### Phase 4: Deployment & Config Audit
18) Audit DEPLOYMENT.md and ROLLBACK.md.
19) Verify commands, env vars, service lists, ports.
20) Compare .env.example against actual code usage.
21) Score and log findings.

### Phase 5: Model Routing Audit
22) Audit MODELS.md against models.yaml and code.
23) Verify routing logic, tier descriptions, focus-to-model mapping.
24) Score and log findings.

### Phase 6: Dashboard & Web Audit
25) Audit API.md dashboard section against Flask routes and templates.
26) Verify template count, page features, URL paths.
27) Score and log findings.

### Phase 7: Database & ORM Audit
28) Audit database docs against src/api/db/models.py.
29) Verify model count, schemas, relationships, constraints.
30) Verify "no raw SQL" claim.
31) Score and log findings.

### Phase 8: Testing & CI Audit
32) Audit test docs against actual test files and CI workflows.
33) Verify test commands and CI steps.
34) Score and log findings.

### Phase 9: Cross-Reference Integrity
35) Scan all markdown links for dead references.
36) Check for contradictions between documents.
37) Verify version and date consistency.

### Phase 10: Build Coverage Matrix
38) Aggregate per-domain scores.
39) Calculate overall coverage and accuracy.
40) Identify best and worst documented domains.

### Phase 11: Execute Fixes
41) Fix CRITICAL findings.
42) Fix HIGH findings with XS/S effort.
43) Fix MEDIUM findings with XS effort.
44) Validate all fixes don't introduce new gaps.
45) Defer remaining items with rationale.

### Phase 12: Recalculate & Report
46) Re-score all domains.
47) Calculate improvement delta.
48) Produce GO/NO-GO with rationale.
49) Publish final report with full metrics.

## Rules
- No finding without code evidence.
- No fix without verification.
- No cosmetic-only changes.
- If uncertain: mark LOW confidence, not HIGH.
- Every batch must have validation evidence.

## Quality Bar
- Primary doc accuracy >90% after fixes.
- No CRITICAL findings remaining.
- Coverage matrix complete for all domains.
- Cross-references clean (no dead links in primary docs).

## Finding Format
For each finding include:
- ID, type (from taxonomy), severity, confidence
- Doc claim with file/line
- Code reality with file/line
- Impact assessment
- Suggested fix with effort estimate
- Status

## Fix Format
For each fix include:
- Finding ID, file modified
- Before/after text
- Validation method
- Status

## Output Requirements
Final report must include:
- Executive summary with key metrics
- Per-domain audit summaries
- Top 10 most impactful findings
- All fixes applied with evidence
- Coverage scores before and after
- Deferred backlog with rationale
- Improvement roadmap priorities
- GO/NO-GO with explicit reasoning

Begin immediately with:
1) Documentation inventory
2) Code baselines
3) Phase 1 audit
Then execute all phases sequentially.
```

---

## 19) Specialized Sub-Prompts (use for targeted audits)

### 19.1 API Contract Audit Only

```md
You are a QA engineer auditing API documentation against actual route implementations.

Scope: API.md, docs/API_ENDPOINT_INVENTORY.md vs src/api/routers/*.py

Task:
1. Count all actual route decorators (@router.get, @router.post, etc.) across all router files.
2. Compare against documented endpoint count.
3. For each router file, verify that its endpoints are documented.
4. Sample-check 20 endpoints for correct HTTP method, path, and handler name.
5. Identify all undocumented endpoints.
6. Identify all documented endpoints that don't exist.
7. Check WebSocket and GraphQL documentation accuracy.
8. Produce findings table with evidence.

Format each finding as:
| Finding | Type | Doc Says | Code Shows | File:Line |
```

### 19.2 Skill Manifest Audit Only

```md
You are a QA engineer auditing skill documentation against actual skill implementations.

Scope: SKILLS.md, aria_skills/SKILL_STANDARD.md vs aria_skills/*/skill.json and aria_skills/*/__init__.py

Task:
1. List all skill directories in aria_skills/ (exclude _template, __pycache__).
2. For each skill, read its skill.json and extract: name, layer, description, tools, dependencies.
3. Verify skill layer against SKILLS.md layer hierarchy.
4. Check if skill has SKILL.md documentation.
5. Verify skill class extends BaseSkill.
6. Check if skill is registered with @SkillRegistry.register.
7. Compare documented skill count against actual count.
8. Identify skills documented in SKILLS.md that don't exist.
9. Identify skills that exist but aren't mentioned anywhere.
10. Produce skill coverage matrix.

Format: Table with columns: Skill Name | Layer (doc) | Layer (code) | Has SKILL.md | Registered | In SKILLS.md | Status
```

### 19.3 Configuration Drift Audit Only

```md
You are a DevOps engineer auditing configuration documentation against actual system configuration.

Scope: DEPLOYMENT.md, .env.example, docker-compose.yml, stacks/brain/docker-compose.yml vs actual code usage.

Task:
1. Extract all environment variables from .env.example.
2. Extract all os.environ/os.getenv references from Python source code.
3. Cross-reference: find vars in code but not in .env.example.
4. Cross-reference: find vars in .env.example but not in code.
5. Verify each env var documented in DEPLOYMENT.md exists in .env.example.
6. Verify Docker service names match between docs and compose.
7. Verify port mappings match between docs and compose.
8. Verify health check URLs match between docs and compose.
9. Verify volume mounts match between docs and compose.
10. Produce config drift findings table.

Format: | Config Item | Doc Value | Code Value | .env.example | Status |
```

### 19.4 Dead Link Scan Only

```md
You are scanning all markdown documentation for broken links.

Scope: All *.md files in repo root and docs/ directory.

Task:
1. Extract all markdown links [text](target) from all .md files.
2. For each link:
   a. If target is a local file path: check if file exists.
   b. If target has an anchor (#section): check if file exists (anchor verification is optional).
   c. If target is a URL: note it as external (don't fetch).
3. Report all dead links with: source file, line number, link text, target, why it's dead.
4. Categorize: MISSING_FILE, WRONG_PATH, MOVED_FILE, DELETED_FILE.
5. Suggest correct target where identifiable.

Format: | Source | Line | Link Text | Target | Status | Suggested Fix |
```

### 19.5 Code Example Verification Only

```md
You are verifying that all code examples in documentation are syntactically valid and reference real APIs.

Scope: All code blocks (``` delimited) in *.md files at repo root and docs/.

Task:
1. Extract all code blocks from documentation files.
2. For Python code blocks:
   a. Check syntax validity (can it parse without SyntaxError?).
   b. Check if imported modules exist in the project.
   c. Check if referenced classes/functions exist in the codebase.
   d. Check if API endpoints referenced exist in routers.
3. For bash/shell code blocks:
   a. Check if referenced scripts/commands exist.
   b. Check if paths referenced exist.
   c. Check if tools referenced are standard or project-specific.
4. Report invalid examples with: source file, line number, code block, issue.

Format: | Source | Line | Language | Issue Type | Code Snippet | Reality |
```

### 19.6 Onboarding Path Audit Only

```md
You are simulating a new developer's onboarding experience through the documentation.

Scope: README.md → ARCHITECTURE.md → DEPLOYMENT.md → CONTRIBUTING.md → SKILLS.md

Task:
1. Follow the README Quick Start instructions literally. Note every point of confusion.
2. Follow the CONTRIBUTING development setup instructions literally. Note gaps.
3. Attempt to understand the architecture from ARCHITECTURE.md. Note unexplained concepts.
4. Attempt to deploy using DEPLOYMENT.md instructions. Note missing steps.
5. Attempt to create a new skill following SKILLS.md → SKILL_CREATION_GUIDE.md. Note gaps.
6. For each friction point:
   a. Is the information missing, wrong, or confusing?
   b. What would a new developer need to know?
   c. How hard is it to figure out from code?
7. Rate onboarding difficulty: 1 (smooth) to 5 (impossible without help).
8. Produce onboarding friction report.

Format: | Step | Document | Section | Friction Type | Severity | What's Missing |
```

---

## 20) Reporting Formats

### 20.1 Standup Format
```md
## Standup [timestamp]
- **Completed**: [phases/domains audited]
- **In progress**: [current audit domain]
- **Findings so far**: X total (C:X H:X M:X L:X)
- **Fixes applied**: X
- **Next**: [upcoming phases]
- **Risks/blockers**: [any impediments]
- **Coverage**: [current overall %]
```

### 20.2 Phase Summary Format
```md
## Phase [N] Summary: [Domain Name]

### Scope
- Docs audited: [list]
- Code files verified: [list]

### Baselines
- Features in code: X
- Features documented: X
- Documentation accuracy: X%

### Findings
| ID | Type | Severity | Summary |
|----|------|----------|---------|
| GAP-XXX | ... | ... | ... |

### Coverage Change
- Before: X% coverage, X% accuracy
- After fixes: X% coverage, X% accuracy

### Fixes Applied
- [FIX-XXX]: [summary]

### Deferred
- [GAP-XXX]: [why]
```

### 20.3 Final Executive Summary Format
```md
## Executive Summary

### Mission
Documentation-vs-implementation gap analysis for Aria Blue v3.0.0.

### Key Metrics
| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Total findings | - | X | - |
| CRITICAL findings | - | X open | - |
| Overall coverage | X% | X% | +X% |
| Overall accuracy | X% | X% | +X% |
| Docs audited | 0 | X | +X |
| Fixes applied | 0 | X | +X |

### Top 5 Most Impactful Findings
1. [GAP-XXX]: [one-line summary]
2. ...

### Domain Grades
| Domain | Grade | Notes |
|--------|-------|-------|
| API | B+ | ... |
| Skills | C | ... |
| Deploy | B | ... |

### Verdict: GO / NO-GO
[Explicit verdict with reasoning]

### Recommendations
1. [Highest priority improvement]
2. [Second priority]
3. [Third priority]
```

---

## 21) Improvement Roadmap Template (for Improvement Mode)

```md
# Documentation Improvement Roadmap

## Quick Wins (XS-S effort, immediate value)
| ID | Improvement | Effort | Impact | Target Doc |
|----|-------------|--------|--------|-----------|
| IMP-001 | ... | XS | HIGH | ... |

## Sprint-Sized Improvements (M effort)
| ID | Improvement | Effort | Impact | Target Doc |
|----|-------------|--------|--------|-----------|
| IMP-010 | ... | M | HIGH | ... |

## Major Improvements (L-XL effort, strategic value)
| ID | Improvement | Effort | Impact | Description |
|----|-------------|--------|--------|-------------|
| IMP-020 | ... | L | HIGH | ... |

## New Documentation Proposals
| ID | Title | Purpose | Audience | Effort | Priority |
|----|-------|---------|----------|--------|----------|
| NEW-001 | Troubleshooting Guide | Common issues and fixes | Operators | M | HIGH |
| NEW-002 | Architecture Decision Records | Record design decisions | Developers | L | MEDIUM |

## Documentation Maintenance Process
- [ ] Bi-weekly doc accuracy scan (automated where possible)
- [ ] New feature = doc update in same PR
- [ ] Quarterly comprehensive audit
- [ ] Dead link checker in CI
```

---

## 22) Automation Opportunities

### 22.1 CI Integration Checks
```md
Propose adding these to CI pipeline:
1. Dead link checker — scan all *.md for broken links
2. Endpoint count validator — compare documented vs actual count
3. Skill manifest validator — check skill.json against directory structure
4. Env var coverage — compare .env.example vs code references
5. Template count validator — compare documented vs actual template count
```

### 22.2 Pre-Commit Hooks
```md
Propose adding these pre-commit checks:
1. Modified .py file has corresponding doc update (advisory, not blocking)
2. New skill directory has SKILL.md (blocking)
3. New router file has endpoint inventory update (advisory)
4. Markdown link validity check (blocking)
```

### 22.3 Documentation Health Dashboard
```md
Propose a periodic documentation health report:
- Run automated checks weekly
- Post results to tasks/doc_health_weekly.md
- Track coverage and accuracy trends over time
- Flag newly introduced gaps
```

---

## 23) Checklist Library Plus (deep set)

### 23.1 Python Docstring Coverage Checklist
- [ ] All public classes have docstrings.
- [ ] All public methods have docstrings.
- [ ] Docstrings match actual parameter names and types.
- [ ] Return types described match actual return types.
- [ ] Raised exceptions are documented.
- [ ] Examples in docstrings are syntactically valid.

### 23.2 API Schema Documentation Checklist
- [ ] All Pydantic request models have field descriptions.
- [ ] All Pydantic response models have field descriptions.
- [ ] Enum values are documented.
- [ ] Optional vs required fields are correctly indicated.
- [ ] Default values are documented.
- [ ] Validation rules are documented.

### 23.3 Docker Service Documentation Checklist
- [ ] Every service in compose has a description in docs.
- [ ] All health check endpoints are documented.
- [ ] All port mappings are documented.
- [ ] All volume mounts are documented.
- [ ] All environment variables per service are documented.
- [ ] Service startup order and dependencies are documented.
- [ ] Profile-specific services (monitoring, sandbox) are documented.

### 23.4 Error Handling Documentation Checklist
- [ ] API error codes are documented.
- [ ] Error response format is documented.
- [ ] Common error scenarios are listed with resolution steps.
- [ ] Circuit breaker behavior is documented.
- [ ] Rate limiting behavior is documented.
- [ ] Authentication failure behavior is documented.

### 23.5 Security Documentation Checklist
- [ ] Authentication mechanism is documented.
- [ ] Authorization rules are documented.
- [ ] Security middleware features are accurately listed.
- [ ] Prompt injection scanning behavior is documented.
- [ ] Secret management approach is documented.
- [ ] Soul/kernel immutability rules are documented.
- [ ] Input validation patterns are documented.

### 23.6 Performance Documentation Checklist
- [ ] Prometheus metrics endpoints are documented.
- [ ] Key metrics names are listed.
- [ ] Grafana dashboard setup is documented.
- [ ] MLX performance benchmarks are documented.
- [ ] Load test methodology is documented.
- [ ] Memory profiling approach is documented.

---

## 24) Multi-Doc Contradiction Detection Patterns

### Pattern 1: Numeric Claims
```
Search for the same metric across multiple docs.
Example: "endpoints" count in README vs API.md vs STRUCTURE.md
If counts differ: CONTRADICTION finding.
```

### Pattern 2: Technology Claims
```
Search for technology names (e.g., "Flask", "FastAPI", versions).
Verify all docs agree on:
- Which technology is used for what
- Version numbers
- Configuration approaches
```

### Pattern 3: File Path References
```
When Doc A references a file path, check if Doc B references the same file differently.
Example: "stacks/brain/.env" vs ".env" vs "stacks/brain/.env.example"
```

### Pattern 4: Process Claims
```
When multiple docs describe the same process (e.g., deployment):
- Are steps consistent?
- Are commands identical?
- Do they reference the same scripts?
```

### Pattern 5: Feature Scope Claims
```
When multiple docs describe what a component does:
- Do they agree on feature set?
- Do they agree on limitations?
- Do they agree on dependencies?
```

---

## 25) Bidirectional Coverage Map Template

### Doc → Code Direction (Does every doc claim have a code reality?)
```md
| Doc File | Section | Claim | Code Evidence | Verified? |
|----------|---------|-------|---------------|-----------|
| ARCHITECTURE.md | Layer Hierarchy | 5 layers L0-L4 | aria_skills/*/skill.json | YES |
| ARCHITECTURE.md | Memory | Working memory sync | aria_mind/memory.py | YES |
| API.md | Endpoints | 222 REST endpoints | src/api/routers/ | PARTIAL |
```

### Code → Doc Direction (Does every code feature have documentation?)
```md
| Code File | Feature | Documented? | Where? | Complete? |
|-----------|---------|-------------|--------|-----------|
| aria_engine/circuit_breaker.py | Circuit breaker | Partial | ARCHITECTURE.md | Missing details |
| aria_engine/streaming.py | Streaming responses | No | - | SILENT feature |
| aria_skills/rpg/ | RPG campaigns | Yes | docs/RPG_SYSTEM.md | Good |
```

---

## 26) Documentation Quality Dimensions

Rate each doc on these 7 dimensions (1-5 scale):

| Dimension | Definition | 1 (Poor) | 5 (Excellent) |
|-----------|-----------|----------|---------------|
| **Accuracy** | Content matches code reality | Multiple lies | Every claim verified |
| **Completeness** | All features covered | Major gaps | Full coverage |
| **Currency** | Reflects current state | Many versions behind | Up to date |
| **Clarity** | Easy to understand | Confusing/ambiguous | Crystal clear |
| **Actionability** | Reader can act on it | Abstract/vague | Step-by-step verified |
| **Navigation** | Easy to find what you need | No structure | Logical, linked, sectioned |
| **Consistency** | Agrees with other docs | Contradictions | Harmonized |

### Overall Doc Quality Score
```
Quality = (Accuracy × 3 + Completeness × 2 + Currency × 2 + Clarity × 1 + Actionability × 1 + Navigation × 0.5 + Consistency × 0.5) / 10
```

Accuracy is triple-weighted because inaccurate docs are worse than missing docs.

---

## 27) Risk Assessment for Documentation Gaps

### Risk Categories for Doc Gaps
| Category | Description | Example |
|----------|------------|---------|
| **Security Risk** | Gap could cause security misconfiguration | Missing auth setup steps |
| **Data Risk** | Gap could cause data loss or corruption | Wrong backup procedure |
| **Operational Risk** | Gap could cause service outage | Wrong deployment command |
| **Development Risk** | Gap could cause developer confusion | Wrong architecture description |
| **Onboarding Risk** | Gap could prevent new contributor setup | Missing prerequisites |
| **Integration Risk** | Gap could cause integration failures | Wrong API contract |

### Risk Scoring
```
Risk Score = Likelihood × Impact
- Likelihood: 1 (unlikely) to 5 (will definitely cause problems)
- Impact: 1 (minor confusion) to 5 (critical failure)
- Risk Score: 1-25
- High: >15, Medium: 6-15, Low: 1-5
```

---

## 28) Ready-to-Paste "Ultra Long" Super Prompt

```md
You are now the PO + Technical Writer + Principal Engineer + QA Lead for a high-discipline documentation-vs-implementation gap analysis sprint.

You must deliver measurable documentation quality outcomes with rigorous evidence and comprehensive coverage scoring.

### Non-Negotiable Exclusions
- aria_memories/**
- aria_souvenirs/**
No modifications under these paths.

### Primary Outcomes
1. Audit ALL primary documentation against actual code implementation.
2. Discover every documentation lie, phantom feature, silent feature, and drift.
3. Score documentation coverage and accuracy per domain.
4. Fix all CRITICAL and HIGH-severity gaps.
5. Produce a prioritized improvement roadmap for remaining gaps.
6. Deliver a GO/NO-GO verdict on documentation quality.

### Required Files
- tasks/gap_analysis_plan.md
- tasks/gap_analysis_inventory.md
- tasks/gap_analysis_findings.md
- tasks/gap_analysis_coverage.md
- tasks/gap_analysis_fixes.md
- tasks/gap_analysis_risk_register.md
- tasks/gap_analysis_final_report.md

### Source of Truth
Code > Config > Tests > Primary Docs > Secondary Docs.
When docs disagree with code, docs are wrong.

### Gap Taxonomy (use exactly these types)
- LIE: Doc makes false claim
- PHANTOM: Doc describes nonexistent feature
- SILENT: Code feature with zero documentation
- DRIFT: Doc was once correct, code evolved past it
- CONFIG_MISMATCH: Documented config differs from actual
- INCOMPLETE: Doc covers topic but misses major aspects
- STALE_EXAMPLE: Code examples are outdated
- CONTRADICTION: Multiple docs disagree
- DEAD_LINK: Link target doesn't exist
- MISLEADING: Technically true but creates wrong impression

### Severity Levels
- CRITICAL: Blocks setup/causes data loss/security issue
- HIGH: Causes deployment/ops failure
- MEDIUM: Causes moderate confusion
- LOW: Minor inaccuracy
- INFO: Quality observation

### Mandatory Execution
Phase 0: Setup
- Create all required artifacts
- Build documentation inventory (all .md files, classify as Primary/Secondary/Tertiary)
- Establish code baselines (endpoint count, skill count, model count, service count, template count)

Phase 1: Architecture Audit
- ARCHITECTURE.md against actual code structure
- Layer diagrams, data flows, service topology
- Memory architecture, focus personas, agent roles

Phase 2: API Audit
- API.md, docs/API_ENDPOINT_INVENTORY.md against src/api/routers/
- Endpoint counts, route verification, schema checks
- GraphQL, WebSocket, security middleware

Phase 3: Skill System Audit
- SKILLS.md, SKILL_STANDARD.md against aria_skills/
- Skill counts, layer verification, manifest accuracy
- Per-skill documentation coverage

Phase 4: Deployment Audit
- DEPLOYMENT.md, ROLLBACK.md against docker-compose, .env, scripts
- Commands, env vars, ports, services
- First-run and setup instructions

Phase 5: Model Routing Audit
- MODELS.md against models.yaml, focus.py, LiteLLM config
- Tier descriptions, routing logic, model catalog

Phase 6: Dashboard Audit
- API.md dashboard section against src/web/
- Template counts, page features, Flask routes

Phase 7: Database Audit
- Database docs against src/api/db/models.py
- Model counts, schema names, relationships
- "No raw SQL" claim verification

Phase 8: Testing & CI Audit
- Test docs against tests/, .github/workflows/
- Commands, CI steps, coverage

Phase 9: Cross-Reference Integrity
- All markdown links scanned for dead targets
- Inter-document contradictions detected
- Version/date consistency checked

Phase 10: Coverage Matrix
- Per-domain coverage and accuracy scores
- Overall scores calculated
- Best/worst domains identified

Phase 11: Execute Fixes
- Fix CRITICAL findings (all)
- Fix HIGH findings (XS/S effort)
- Fix MEDIUM findings (XS effort)
- Validate each fix
- Defer rest with rationale

Phase 12: Final Report
- Re-score all domains
- Calculate improvement delta
- Produce GO/NO-GO
- Publish comprehensive final report

### Hard Rules
- No finding without code evidence (file + line).
- No fix without verification.
- No cosmetic-only changes counted as fixes.
- No confidence inflation — mark honestly.
- No scope creep into code changes.
- Every phase must end with findings logged and domain scored.

### Quality Bar
- Primary doc accuracy >90% after fixes
- No CRITICAL findings remaining
- Coverage matrix complete for all domains
- Cross-references clean in primary docs
- Final report includes before/after metrics

### Finding Format
ID | Type | Severity | Confidence | Doc (file:line) | Claim | Code (file:line) | Reality | Impact | Fix | Effort | Status

### Fix Format
Finding ID | File | Before | After | Validation | Status

### Reporting
At each phase boundary, provide:
- Findings so far (count by type and severity)
- Fixes applied
- Current coverage estimate
- Next phase plan

Final report includes:
- Executive summary with key metrics and delta
- Per-domain audit summaries
- Top 10 most impactful findings
- All fixes with evidence
- Coverage scores before/after
- Deferred backlog with rationale
- Improvement roadmap (prioritized)
- Automation recommendations
- GO/NO-GO with explicit reasoning

Begin immediately with:
1) Documentation inventory
2) Code baselines
3) Phase 1 architecture audit
Then proceed through all phases in order.
```

---

## 29) Additional Story Templates

### 29.1 Gap Finding Story Template
```md
## Finding [GAP-XXX]: [Title]

### Documentation Claim
- **File**: [doc path]
- **Line(s)**: [line numbers]
- **Quote**: "[exact text from documentation]"

### Code Reality
- **File(s)**: [code path(s)]
- **Line(s)**: [line numbers]
- **Evidence**: [what the code actually shows]

### Classification
- **Type**: [from taxonomy]
- **Severity**: [CRITICAL/HIGH/MEDIUM/LOW/INFO]
- **Confidence**: [HIGH/MEDIUM/LOW]
- **Domain**: [which audit domain]

### Impact
[Who is affected and how — be specific]

### Suggested Fix
[Exact text to change, or new text to add]

### Effort
[XS/S/M/L/XL with brief justification]

### Related Findings
[Other findings that are related, if any]

### Status
[FOUND / CONFIRMED / FIXED / DEFERRED / WONT_FIX]
```

### 29.2 Fix Validation Template
```md
## Fix [FIX-XXX] for [GAP-XXX]

### Change
- **File**: [path]
- **Before** (lines X-Y):
```
[old text]
```
- **After**:
```
[new text]
```

### Validation
- **Method**: [how correctness was verified]
- **Verified Against**: [code file and line]
- **Cross-Reference Check**: [did any other doc reference this info?]
- **Side Effects**: [any other docs affected?]
- **Result**: PASS / FAIL

### Status
APPLIED / REVERTED / PENDING
```

### 29.3 Deferred Item Template
```md
## Deferred: [GAP-XXX] — [Title]

### Reason for Deferral
[Why this can't or shouldn't be fixed now]

### What Would Be Needed
[Information or action needed to fix this]

### Risk of Leaving Unfixed
[What happens if this stays as-is]

### Recommended Sprint
[When to address this — next sprint, quarterly cleanup, etc.]
```

---

## 30) Final Usage Guidance

### Choosing Your Mode

| Situation | Recommended Mode |
|-----------|-----------------|
| First full audit of documentation | **Strict** (Section 4.1) |
| Broad scan across many docs quickly | **Aggressive** (Section 4.2) |
| Deep dive into one problem area | **Deep** (Section 4.3) |
| Planning a doc improvement campaign | **Improvement** (Section 4.4) |
| Auditing just API docs | **Sub-prompt 19.1** |
| Auditing just skill manifests | **Sub-prompt 19.2** |
| Checking for config drift | **Sub-prompt 19.3** |
| Scanning for dead links only | **Sub-prompt 19.4** |
| Verifying code examples | **Sub-prompt 19.5** |
| Testing onboarding experience | **Sub-prompt 19.6** |

### Combining Modes
You can chain modes:
1. Start with **Aggressive** to get broad coverage fast.
2. Use **Deep** on the worst-scoring domains.
3. Switch to **Improvement** for the roadmap.

### Frequency
- **Full audit**: Quarterly or after major releases
- **Targeted audit**: After any sprint that changes >20 files
- **Dead link scan**: Weekly (automate in CI)
- **Config drift check**: After any Docker/env changes

### This prompt is designed to scale
- Small repo: Use Section 4.1 or 4.2, single pass
- Large repo: Use Section 18 (Ultra Long), multi-phase
- Targeted audit: Use Section 19 sub-prompts
- Ongoing maintenance: Use Section 22 automation proposals

---

## Appendix A: Common Aria-Specific Gap Patterns

Based on the Aria Blue repository structure, watch for these common gap patterns:

### A.1 Skill Layer Mismatch
Skills may have been reclassified (moved between layers) without updating SKILLS.md or skill.json.
Verification: Cross-reference every skill.json "layer" field against SKILLS.md hierarchy table.

### A.2 Endpoint Count Drift
The API grows constantly. Documented counts (e.g., "222 REST endpoints") quickly become stale.
Verification: Run `python3 scripts/generate_endpoint_matrix.py` and compare.

### A.3 Docker Service Drift
New services get added to docker-compose.yml without updating DEPLOYMENT.md or ARCHITECTURE.md.
Verification: Parse service names from compose and compare against doc mentions.

### A.4 Model Catalog Drift
models.yaml evolves (new models added, tiers changed) without updating MODELS.md.
Verification: Compare documented model list against models.yaml entries.

### A.5 Focus Persona Drift
Focus personas in aria_mind/soul/focus.py may have been added/removed without updating ARCHITECTURE.md.
Verification: Extract persona definitions from focus.py and compare against doc list.

### A.6 Dashboard Template Drift
New dashboard pages get added to src/web/templates/ without updating API.md.
Verification: Count templates and compare against documented count.

### A.7 Test Command Drift
Test commands and CI configurations change without updating README.md or CONTRIBUTING.md.
Verification: Run documented commands and check if they work.

### A.8 Environment Variable Drift
New env vars get added to code without updating .env.example or DEPLOYMENT.md.
Verification: Grep for os.environ/os.getenv and compare against docs.

### A.9 Script Reference Drift
Scripts get renamed, moved, or deleted without updating Makefile, README.md, or DEPLOYMENT.md references.
Verification: Check every script reference in docs against actual scripts/ directory.

### A.10 Cross-Link Decay
As documents are moved, renamed, or deleted, internal markdown links break silently.
Verification: Systematic link scan across all markdown files.

---

## Appendix B: Aria Documentation Source Map

Quick reference for which docs describe which code:

| Code Domain | Primary Doc | Secondary Docs | Code Root |
|-------------|-------------|----------------|-----------|
| Overall architecture | ARCHITECTURE.md | README.md | Multiple |
| Skill system | SKILLS.md | SKILL_STANDARD.md, SKILL_CREATION_GUIDE.md | aria_skills/ |
| API endpoints | API.md | docs/API_ENDPOINT_INVENTORY.md | src/api/routers/ |
| Database/ORM | API.md (db section) | src/api/db/MODELS.md | src/api/db/ |
| Dashboard | API.md (dashboard section) | - | src/web/ |
| Model routing | MODELS.md | aria_models/README.md | aria_models/ |
| Deployment | DEPLOYMENT.md | ROLLBACK.md | stacks/brain/ |
| Development setup | CONTRIBUTING.md | README.md (quick start) | pyproject.toml |
| Testing | README.md (tests section) | CONTRIBUTING.md | tests/ |
| Soul/identity | aria_mind/SOUL.md | aria_mind/IDENTITY.md | aria_mind/soul/ |
| Security | aria_mind/SECURITY.md | - | aria_mind/security.py |
| Agent system | aria_mind/AGENTS.md | ARCHITECTURE.md | aria_agents/ |
| Engine | - | ARCHITECTURE.md | aria_engine/ |
| Memory | aria_mind/MEMORY.md | ARCHITECTURE.md | aria_mind/memory.py |
| RPG system | docs/RPG_SYSTEM.md | aria_mind/RPG.md | aria_skills/rpg/ |
| Repository layout | STRUCTURE.md | README.md | Root |
| Changelog | CHANGELOG.md | - | - |
| CI/CD | - | CONTRIBUTING.md | .github/workflows/ |

---

## Appendix C: Verification Command Quick Reference

```bash
# Endpoint count
grep -rn "@router\." src/api/routers/ | wc -l

# Skill count
ls -d aria_skills/*/ | grep -v _template | grep -v __pycache__ | wc -l

# ORM model count
grep -c "class.*Base)" src/api/db/models.py

# Docker service count
grep "^\s\+[a-z]" stacks/brain/docker-compose.yml | grep -v "#" | grep ":" | wc -l

# Template count
ls src/web/templates/*.html 2>/dev/null | wc -l

# Env vars in code
grep -rn "os\.environ\|os\.getenv" src/ aria_engine/ aria_skills/ aria_mind/ aria_agents/ 2>/dev/null | grep -v __pycache__ | wc -l

# Dead links in docs
grep -roh "\[.*\]([^)]*\.md[^)]*)" *.md docs/*.md 2>/dev/null

# Architecture check
python3 tests/check_architecture.py

# Run all tests
pytest tests/ -v --timeout=60

# Smoke check
python3 tests/e2e/runtime_smoke_check.py
```

---

## Appendix D: Gap Analysis Metrics Glossary

| Metric | Definition | Formula |
|--------|-----------|---------|
| **Coverage** | % of code features that have any documentation | documented_features / total_features × 100 |
| **Accuracy** | % of documented claims that match code reality | verified_claims / total_claims × 100 |
| **Completeness** | % of each feature's aspects that are documented | documented_aspects / total_aspects × 100 |
| **Currency** | How recent the documentation reflects code changes | (features_up_to_date / documented_features) × 100 |
| **Gap Density** | Findings per 100 lines of documentation | (findings / total_doc_lines) × 100 |
| **Fix Rate** | % of findings that were fixed in this sprint | fixed_findings / total_findings × 100 |
| **Risk Score** | Weighted sum of unresolved findings | Σ(severity_weight × finding_count) |
| **Improvement Delta** | Change in accuracy after fixes | accuracy_after - accuracy_before |

### Severity Weights for Risk Score
- CRITICAL: 10
- HIGH: 5
- MEDIUM: 2
- LOW: 1
- INFO: 0

---

*This prompt pack (PO Doc-Implementation Gap Analysis v1) is designed to be expanded with per-subsystem prompts, automated tooling integration, and ongoing maintenance workflows as the documentation practice matures.*
