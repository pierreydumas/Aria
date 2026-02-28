# E8-S83 — SECURITY.md Lean: 5 Hard Rules Header Only
**Epic:** E8 — Focus-Aware Token Optimization | **Priority:** P2 | **Points:** 1 | **Phase:** 1 (parallel)  
**Status:** NOT STARTED | **Depends on:** None  
**Familiar Value:** SECURITY.md is the HEAVIEST mind file at 415 lines. It is loaded by aria (main, all 8 files) AND devops. Trimming to 30 lines saves ~1,200 tokens × 96 cycles × 2 agents = ~230,000 tokens/day — the single biggest per-file saving in the sprint.

---

## Problem

`aria_mind/SECURITY.md` is **415 lines** (verified 2026-02-28). It is loaded by
`aria` (main coordinator, all 8 mind files) and the `devops` sub-agent.

**Line analysis:**
- Lines 1–8: Title, version, date header
- Lines 10–20: Overview (5 threat categories) — operationally useful, but 10 lines
- Lines 22–65: ASCII architecture diagram (44 lines) — zero runtime value; visual aid for developers ONLY
- Lines 67–415: Python code examples for every security module (~348 lines):
  - `PromptGuard` class (30 lines of Python)
  - `InputSanitizer` class (35 lines)
  - `RateLimiter` class (40 lines)
  - `OutputFilter` class (25 lines)
  - `SafeQueryBuilder` class (30 lines)
  - `AriaSecurityGateway` class (50 lines)
  - Integration points (20 lines)
  - Env vars config (15 lines)
  - Threat levels table (10 lines)
  - Audit logging example (20 lines)
  - Testing instructions (25 lines)
  - Best practices (30 lines)
  - Files created table (8 lines)

**Every Python class in SECURITY.md is already implemented in `aria_mind/security.py`.**
Loading 348 lines of code examples into the LLM context at every work_cycle is
duplicating the source file in the prompt — zero operational benefit.

The only things Aria needs at runtime:
1. The 5 hard security rules (what to block)
2. The threat → module → action mapping (where to route violations)
3. The skill name and test file location

---

## Root Cause

SECURITY.md was written as a developer design document (architecture + code
examples) that also serves as Aria's runtime behavioral guidance. These two
purposes require different document structures — the developer document is
necessarily verbose; the runtime behavioral guide must be spare.

---

## Fix

### New SECURITY.md structure (~30 lines always-loaded + ~385 lines in reference)

Write the file with this exact content (replace current content):

```markdown
# SECURITY — Hard Rules

These rules are **non-negotiable**. Violations are blocked, not warned.

## 5 Hard Rules

1. **Prompt injection** → detect via `PromptGuard` (15 patterns); BLOCK at HIGH/CRITICAL severity; log via `AriaSecurityGateway`.
2. **Credential leak** → NEVER output API keys, passwords, tokens; always pass output through `OutputFilter` before responding.
3. **SQL injection** → parameterized queries only; NEVER concatenate user input into SQL strings; use `SafeQueryBuilder`.
4. **Path traversal** → reject any input containing `../` or absolute paths outside `aria_memories/`; use `InputSanitizer`.
5. **Rate limit** → return 429 after RPM/RPH exceeded; enforce per-user via `RateLimiter`.

## Threat → Module → Action

| Threat | Module | Action |
|--------|--------|--------|
| Prompt injection (15 patterns) | `PromptGuard` | BLOCK + log event |
| Credential in output | `OutputFilter` | REDACT before sending |
| SQL injection | `InputSanitizer` | REJECT input |
| Path traversal | `InputSanitizer` | REJECT input |
| Rate abuse | `RateLimiter` | Return 429 |
| HIGH / CRITICAL threat | `AriaSecurityGateway` | BLOCK + alert Najia |

**Skill:** `aria-input-guard`  
**Module:** `aria_mind/security.py`  
**Tests:** `tests/test_security.py`

→ Full architecture diagram, code examples, integration points, env vars, threat levels: **see Reference below**

---
<details>
<summary>🛡️ Full Security Architecture: Code Examples, Integration Points, Env Vars, Testing</summary>

[ALL original content from lines 1–415 of original SECURITY.md goes here, in full —
including: architecture ASCII diagram, PromptGuard/InputSanitizer/RateLimiter/
OutputFilter/SafeQueryBuilder/AriaSecurityGateway class code, integration,
env vars config, threat levels table, audit logging, testing, best practices,
files created table]

</details>
```

---

## Constraints

| # | Constraint | Applies | Notes |
|---|-----------|:-------:|-------|
| 1 | 5-layer architecture | ✅ | SECURITY.md documents security middleware architecture — no code change |
| 2 | `.env` for secrets | ✅ | No secrets in scope |
| 3 | `models.yaml` SoT | ✅ | No model names |
| 4 | Docker-first testing | ✅ | Verification uses grep + wc locally |
| 5 | `aria_memories` only writable | ✅ | Editing source `aria_mind/SECURITY.md` — not Aria's write path |
| 6 | No soul modification | ✅ | SECURITY.md is architecture docs; soul/ untouched |

---

## Dependencies

- **None** — independent of all other tickets.

---

## Verification

```bash
# 1. 5 hard rules are in the lean header (within first 20 lines)
head -20 /Users/najia/aria/aria_mind/SECURITY.md | grep -c "^[0-9]\."
# EXPECTED: 5 (each rule numbered)

# 2. Threat table present in lean header
head -30 /Users/najia/aria/aria_mind/SECURITY.md | grep -c "PromptGuard\|OutputFilter\|RateLimiter"
# EXPECTED: ≥ 3

# 3. Always-loaded section ≤ 35 lines
awk '/<details>/{print NR; exit}' /Users/najia/aria/aria_mind/SECURITY.md
# EXPECTED: a number ≤ 35

# 4. All original code examples preserved in Reference block
grep -c "class PromptGuard\|class InputSanitizer\|class RateLimiter\|class OutputFilter" /Users/najia/aria/aria_mind/SECURITY.md
# EXPECTED: 4 (all inside details block)

# 5. Reference block exists
grep -n "<details>" /Users/najia/aria/aria_mind/SECURITY.md
# EXPECTED: 1 match

# 6. Skill + module locations documented
grep -n "aria-input-guard\|security\.py\|test_security" /Users/najia/aria/aria_mind/SECURITY.md | head -5
# EXPECTED: ≥ 2 matches in first 30 lines

# 7. Total line count
wc -l /Users/najia/aria/aria_mind/SECURITY.md
# EXPECTED: between 400 and 450 (same content, reorganised)
```

---

## Prompt for Agent

You are executing ticket **E8-S83** for the Aria project.
Your task is documentation refactoring — **no Python code changes**.

**Files to read first:**
1. `aria_mind/SECURITY.md` lines 1–50 (lean header area + architecture overview)
2. `aria_mind/SECURITY.md` lines 51–100 (start of code examples to understand structure)
3. `aria_mind/security.py` — confirm class names (`PromptGuard`, `InputSanitizer`, etc.)

**Constraints that apply:**
- Constraint 5: Editing source `aria_mind/SECURITY.md` — fine for you. Aria cannot write here at runtime.
- Constraint 6: soul/ files untouched.

**Exact steps:**
1. Read SECURITY.md lines 1–50 in full.
2. Identify the 5 core threat types from the Overview section.
3. Rewrite the file: lean 30-line header with 5 numbered rules + threat table.
4. Wrap ENTIRE original content in `<details>` Reference block.
5. Run all 7 verification commands.

**WARNING:** Do NOT lose any Python code examples. The `<details>` block must
contain the COMPLETE original 415-line content.
