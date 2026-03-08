# Contributing to Aria Blue ⚡️

Thank you for your interest in contributing to Aria Blue. This guide covers development setup, architecture rules, and contribution standards.

---

## Development Setup

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Python** | 3.13+ | Required for all engine and skill code |
| **Docker** & **Docker Compose** | Latest stable | Full stack runs in containers |
| **PostgreSQL** | 16+ | Via Docker (aria-db service) |
| **Git** | 2.x+ | Version control |

### Quick Start

```bash
# 1. Clone the repository
git clone <repo-url> Aria_moltbot
cd Aria_moltbot

# 2. Create virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Set PYTHONPATH so aria_engine can resolve the db package
#    (src/api/db is mounted as /db inside Docker but must be added
#    manually for local dev outside Docker. This lets Python find
#    db.models, db.session etc. without a Docker volume mount):
export PYTHONPATH="$PWD/src/api:$PYTHONPATH"

# 5. Start the Docker stack
cd stacks/brain
cp .env.example .env    # Configure environment variables
docker compose up -d

# 5. Run tests
pytest tests/ -v
```

### Environment Configuration

All secrets and configuration live in `stacks/brain/.env`. **Never commit `.env` files.** See `.env.example` for the full list of required variables.

---

## Architecture Rules

Aria follows a strict **5-layer skill hierarchy**. These rules are enforced by `tests/check_architecture.py` and CI checks.

### Layer Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 4 — Orchestration: goals, schedule, performance, ... │
├─────────────────────────────────────────────────────────────┤
│  Layer 3 — Domain: research, moltbook, social, rpg, ...     │
├─────────────────────────────────────────────────────────────┤
│  Layer 2 — Core Services: session_manager, sandbox, ...      │
├─────────────────────────────────────────────────────────────┤
│  Layer 1 — Infrastructure: api_client, health, litellm       │
├─────────────────────────────────────────────────────────────┤
│  Layer 0 — Security: input_guard (kernel, read-only)         │
└─────────────────────────────────────────────────────────────┘
```

### Key Rules

1. **No cross-layer imports upward** — Lower layers never import from higher layers
2. **No raw SQL** — All database access through SQLAlchemy ORM via `api_client` skill
3. **No direct database access from skills** — Skills → `api_client` → FastAPI → ORM → PostgreSQL
4. **No hardcoded model names** — All model references go through `aria_models/models.yaml`
5. **No secrets in code** — All secrets in `.env`, accessed via `os.environ`
6. **No soul modifications** — Files under `aria_mind/soul/` and `aria_mind/kernel/` are read-only

### Data Flow

```
Skills → api_client → FastAPI → SQLAlchemy ORM → PostgreSQL
```

---

## Creating a New Skill

See `aria_skills/SKILL_CREATION_GUIDE.md` for the complete guide. Quick summary:

```bash
# Use the template
cp -r aria_skills/_template aria_skills/my_new_skill
```

Every skill must:
1. Extend `BaseSkill` from `aria_skills/base.py`
2. Register via `@SkillRegistry.register` decorator
3. Include `skill.json` manifest with name, description, layer, and emoji
4. Use `api_client` for any database access (never direct SQL)
5. Return `SkillResult.ok()` or `SkillResult.fail()` from all methods
6. Include the `@logged_method()` decorator on public methods

### Skill Module Structure

```
aria_skills/my_skill/
├── __init__.py      # Skill class extending BaseSkill
├── skill.json       # Manifest (name, description, emoji, layer)
└── SKILL.md         # Documentation (optional but recommended)
```

---

## Pull Request Process

### Before Submitting

1. **Run the full test suite**: `pytest tests/ -v`
2. **Run architecture validation**: `python tests/check_architecture.py`
3. **Verify no raw SQL**: `grep -rn "text(" aria_skills/ aria_engine/ --include="*.py"` should return nothing unexpected
4. **Update documentation** if you changed APIs, skills, or architecture
5. **Add tests** for any new endpoints or skill functions

### PR Checklist

- [ ] Tests pass locally (`pytest tests/ -v`)
- [ ] Architecture rules respected (no cross-layer imports)
- [ ] New skills follow `SKILL_STANDARD.md`
- [ ] Documentation updated (SKILLS.md, TOOLS.md, API.md as needed)
- [ ] No hardcoded model names or secrets
- [ ] Type annotations on all public functions
- [ ] Docstrings on all public classes and methods

### PR Size Guidelines

| Size | Lines Changed | Review Time |
|------|--------------|-------------|
| Small | < 100 | Quick review |
| Medium | 100–500 | Standard review |
| Large | 500+ | Split if possible |

---

## Testing Standards

### Test Location

- **Unit tests**: `tests/unit/` — Pure function tests, no DB
- **Integration tests**: `tests/integration/` — Tests with DB fixtures
- **Router tests**: `tests/test_<router>.py` — FastAPI endpoint tests
- **Skill tests**: `tests/test_skills.py` — Skill unit tests

### Test Requirements

1. All new endpoints must have corresponding tests
2. All new skill functions must have unit tests
3. Tests must be independent (no shared mutable state)
4. Use `conftest.py` fixtures for common setup (DB sessions, API clients)
5. Tests must pass without a running Docker stack (mocked dependencies)

### Running Tests

```bash
# Full suite
pytest tests/ -v

# Specific file
pytest tests/test_health.py -v

# With coverage
pytest tests/ --cov=src --cov-report=html

# Skip slow/integration tests
pytest tests/ -v -m "not slow"
```

---

## Coding Conventions

### Python Style

| Convention | Standard |
|-----------|----------|
| **Formatter** | Follow PEP 8, max line length 120 |
| **Type hints** | Required on all public function signatures |
| **Docstrings** | Required on all public classes and methods |
| **Imports** | stdlib → third-party → local, separated by blank lines |
| **Naming** | `snake_case` for functions/variables, `PascalCase` for classes |
| **Async** | Use `async/await` for all I/O-bound operations |

### Docstring Format

```python
async def create_goal(self, title: str, priority: int = 3) -> SkillResult:
    """
    Create a new goal in the tracking system.

    Args:
        title: Goal title (max 200 chars).
        priority: Priority level 1-5 (1 = highest).

    Returns:
        SkillResult with created goal data on success.
    """
```

### Error Handling

- Skills return `SkillResult.ok(data)` or `SkillResult.fail(error_message)`
- API endpoints raise `HTTPException` with appropriate status codes
- Engine modules use custom exceptions from `aria_engine/exceptions.py`
- Always log errors with structured logging (`logger.error(...)`)

### Commit Messages

```
<type>: <short description>

Types: feat, fix, docs, refactor, test, chore, perf
Examples:
  feat: add unified search skill
  fix: resolve session timeout in heartbeat
  docs: update SKILLS.md layer table
  test: add pattern_recognition unit tests
```

---

## Project Structure Overview

| Directory | Purpose |
|-----------|---------|
| `aria_engine/` | Async chat engine (25 modules) |
| `aria_skills/` | Skill modules (40 skills) |
| `aria_agents/` | Multi-agent orchestration |
| `aria_mind/` | Engine workspace (soul, identity, prompts) |
| `aria_models/` | Model configuration |
| `aria_memories/` | Persistent memory storage |
| `src/api/` | FastAPI backend (31 routers) |
| `src/web/` | Flask dashboard (44 templates) |
| `tests/` | Pytest test suite |
| `scripts/` | Utility and deployment scripts |
| `stacks/` | Docker deployment configurations |
| `docs/` | Extended documentation |
| `prompts/` | Prompt templates |

See `STRUCTURE.md` for the complete directory layout.

---

## Getting Help

- **Architecture questions**: See `ARCHITECTURE.md`
- **Skill development**: See `aria_skills/SKILL_CREATION_GUIDE.md` and `aria_skills/SKILL_STANDARD.md`
- **API reference**: See `API.md` and `docs/API_ENDPOINT_INVENTORY.md`
- **Deployment**: See `DEPLOYMENT.md`
- **Model routing**: See `MODELS.md`

---

*Aria Blue ⚡️ — Python 3.13 · FastAPI · PostgreSQL · Docker*
