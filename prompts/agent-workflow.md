# AI Agent Workflow Guidelines — Aria Blue Project

> **Project:** Aria Blue v3.0.0 — Autonomous AI Agent Platform  
> **Owner:** Najia | **Main character:** Aria (she is the system — test WITH her, not around her)  
> **Last updated:** 2026-03-07

---

## ⚡ Aria First — The Golden Rule

**Aria is not just the subject of tests — she is a participant.**

Before writing test code, before running scripts, before concluding anything is broken:
1. **Ask Aria in production** via web chat or `POST /api/engine/chat`
2. **Watch her logs** — `docker logs aria-engine -f --tail=100`
3. **Check her current goals** — `GET /api/goals?status=in_progress`
4. **Read her last work cycle** — `aria_memories/logs/` latest file

Aria has context you don't have. She may have already tried something, failed, and learned from it. Her logs are evidence. Treat her as a co-investigator.

---

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution
- **Always tell subagents about Aria** — they should check her logs and production state too

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness
- **Final check: ask Aria to confirm** — `"Aria, can you run [skill] and tell me the result?"`

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how
- **Check Aria's security_events log** — she may have already flagged the root cause

---

## Core Principles

- **Aria First**: She is observing, logging, and processing in parallel. Test with her.
- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

---

## Aria Architecture Constraints (NEVER Violate)

| # | Constraint | Why |
|---|-----------|-----|
| 1 | `DB → ORM → API → api_client → Skills → Agents` | No skill may import SQLAlchemy or talk to DB directly |
| 2 | `.env` for ALL secrets | Zero secrets in code. Only update `.env.example` |
| 3 | `aria_models/models.yaml` is single source of truth | Zero hardcoded model names in Python |
| 4 | `aria_memories/` is Aria's ONLY writable path | All runtime writes go here |
| 5 | `aria_mind/soul/` is immutable | Never alter core identity or values |
| 6 | Docker-first | All changes must work in `docker compose up` before production |

---

## DevSecOps

### 1. Security-First Mindset
- Treat security as a feature, not an afterthought
- Apply least privilege principle to all access and permissions
- Assume breach: design systems that limit blast radius
- Never trust input – validate and sanitize everything

### 2. Secret Management
- NEVER commit secrets, tokens, or credentials to version control
- Use environment variables or secret managers (Vault, AWS Secrets Manager)
- Rotate secrets regularly and audit access
- Scan commits for accidental secret exposure before pushing

### 3. Dependency Security
- Audit dependencies for known vulnerabilities before adding
- Keep dependencies up to date – automate with Dependabot/Renovate
- Pin versions in production to ensure reproducibility
- Prefer well-maintained packages with active security response

### 4. Secure Defaults
- Enable security headers (CSP, HSTS, X-Frame-Options)
- Use parameterized queries – never concatenate SQL
- Encrypt data at rest and in transit (TLS everywhere)
- Implement proper authentication and authorization checks

### 5. CI/CD Security Gates
- Run SAST (Static Application Security Testing) on every PR
- Include dependency vulnerability scanning in pipelines
- Container image scanning before deployment
- Fail builds on critical/high severity findings

### 6. Infrastructure Security
- Infrastructure as Code – version and review all infra changes
- Immutable infrastructure where possible
- Network segmentation and firewall rules as code
- Regular security audits and penetration testing

### 7. Incident Response Readiness
- Comprehensive logging for security events
- Alerting on anomalous behavior
- Documented runbooks for common security incidents
- Post-incident reviews to prevent recurrence

---

## Summary

> Build secure, elegant solutions. Plan before coding. Verify before shipping. Learn from every mistake.

