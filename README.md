# Aria Blue ⚡️ — Autonomous AI Agent Platform

[![Python](https://img.shields.io/badge/Python-3.13+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-v3.0_API-009688.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)
[![Aria Engine](https://img.shields.io/badge/Aria_Engine-Gateway-purple.svg)](https://github.com/Najia-afk/Aria_moltbot)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![License](https://img.shields.io/badge/License-Source%20Available-orange.svg)](#license)

<img src="aria_mind/aria-profile-v1.png" alt="Aria Blue" width="180" align="right" style="margin-left: 20px; border-radius: 10px;">

Aria is an autonomous AI agent that **thinks like a CEO**: she analyzes tasks, delegates to specialized focus personas, runs parallel roundtable discussions across domains, and synthesizes results — all on a self-driven work cycle with goal tracking, persistent memory, and full observability.

Built on a native Python engine (`aria_engine`) with multi-model LLM routing via LiteLLM (OpenRouter, Moonshot/Kimi, local MLX).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **AI Gateway** | `aria_engine` — native Python agent orchestration, tool execution |
| **LLM Router** | [LiteLLM](https://github.com/BerriAI/litellm) — multi-model routing, automatic failover |
| **Local Inference** | [MLX](https://github.com/ml-explore/mlx) — Apple Silicon Metal GPU (optional) |
| **API** | [FastAPI](https://fastapi.tiangolo.com/) + [Strawberry GraphQL](https://strawberry.rocks/) |
| **ORM** | [SQLAlchemy 2.0](https://www.sqlalchemy.org/) async + [psycopg 3](https://www.psycopg.org/psycopg3/) |
| **Database** | [PostgreSQL 16](https://www.postgresql.org/) — dual databases (Aria + LiteLLM isolated) |
| **Dashboard** | [Flask](https://flask.palletsprojects.com/) + [Chart.js](https://www.chartjs.org/) |
| **Containers** | [Docker Compose](https://docs.docker.com/compose/) — multi-service stack |
| **Monitoring** | [Prometheus](https://prometheus.io/) + [Grafana](https://grafana.com/) |
| **Reverse Proxy** | [Traefik v3.1](https://traefik.io/) — HTTPS, automatic TLS |
| **Language** | Python 3.13 — async throughout, fully typed |

---

## Quick Start

### First-Run Setup (recommended)

The first-run script generates all required secrets and creates your `.env` file:

```bash
# macOS / Linux
chmod +x scripts/first-run.sh
./scripts/first-run.sh
```

```powershell
# Windows PowerShell
.\scripts\first-run.ps1
```

This will:
- Check Docker and Docker Compose are installed
- Copy `.env.example` → `.env`
- Generate secure random passwords for DB, API keys (incl. `ARIA_ADMIN_TOKEN`, `BROWSERLESS_TOKEN`), LiteLLM, Grafana, pgAdmin
- Randomize all host-exposed ports (20000-60000 range) to avoid conflicts
- Optionally prompt for external API keys (OpenRouter, Moonshot)
- Seed clone-safe identity defaults into `aria_memories/memory/` (missing files only)
- Optionally seed working-memory defaults when `ARIA_SEED_WORKING_MEMORY_ON_FIRST_RUN=true`

> Use `--auto` (sh) or `-Auto` (ps1) for non-interactive mode (secrets only, default ports).

### Manual Setup

```bash
# Clone
git clone https://github.com/Najia-afk/Aria_moltbot.git
cd Aria_moltbot

# Configure
cp stacks/brain/.env.example stacks/brain/.env
nano stacks/brain/.env  # Set API keys, DB credentials

# Optional: Start MLX Server (Metal GPU, Apple Silicon)
mlx_lm.server --model nightmedia/Qwen3-VLTO-8B-Instruct-qx86x-hi-mlx \
  --host 0.0.0.0 --port 8080 &

# Deploy (from stacks/brain directory where docker-compose.yml lives)
cd stacks/brain
docker compose up -d

# Verify
docker compose ps
curl http://localhost:8000/api/health
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full guide — API keys, environment config, troubleshooting, and macOS Ollama `launchd` auto-start.

---

## Documentation

| Document | Purpose |
|----------|---------|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System design, layer diagram, data flow, Aria's self-architecture |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | How to deploy, configure, and operate the stack |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** (Ollama macOS launchd) | Persistent Ollama auto-start/auto-restart on macOS (`launchd`) |
| **[SKILLS.md](SKILLS.md)** | Skill system, 5-layer hierarchy, how to create new skills |
| **[MODELS.md](MODELS.md)** | Model routing strategy, tiers, configuration |
| **[API.md](API.md)** | REST API, GraphQL, dashboard, security middleware |
| **[STRUCTURE.md](STRUCTURE.md)** | Repository directory layout |
| **[CHANGELOG.md](CHANGELOG.md)** | Version history |
| **[ROLLBACK.md](ROLLBACK.md)** | Rollback procedures |
| **[docs/RUNBOOK.md](docs/RUNBOOK.md)** | Operational runbook |
| **[docs/API_ENDPOINT_INVENTORY.md](docs/API_ENDPOINT_INVENTORY.md)** | Comprehensive endpoint reference |
| **[docs/RPG_SYSTEM.md](docs/RPG_SYSTEM.md)** | Pathfinder 2e RPG engine |
| **[docs/ANALYSIS_SYSTEM.md](docs/ANALYSIS_SYSTEM.md)** | Sentiment & pattern analysis |

### Source-of-Truth Files

These canonical files contain the live, authoritative data. Don't duplicate their contents — reference them.

| Data | Source |
|------|--------|
| Model catalog & routing | [`aria_models/models.yaml`](aria_models/models.yaml) |
| Skill registry | [`aria_skills/*/skill.json`](aria_skills/) |
| API routers | [`src/api/routers/`](src/api/routers/) |
| ORM models | [`src/api/db/models.py`](src/api/db/models.py) |
| Docker services | [`docker-compose.yml`](docker-compose.yml) (includes [`stacks/brain/docker-compose.yml`](stacks/brain/docker-compose.yml)) |
| Focus personas | [`aria_mind/soul/focus.py`](aria_mind/soul/focus.py) |
| Agent roles | [`aria_agents/base.py`](aria_agents/base.py) |
| Dashboard templates | [`src/web/templates/`](src/web/templates/) |
| Test suite | [`tests/`](tests/) |
| Skill standard | [`aria_skills/SKILL_STANDARD.md`](aria_skills/SKILL_STANDARD.md) |

---

## Running Tests

```bash
# Full suite
pytest tests/ -v

# Architecture compliance
pytest tests/test_architecture.py -v

# With coverage
pytest --cov=aria_skills --cov=aria_agents --cov-report=html

# Inside Docker
make test
```

See [Makefile](Makefile) for all shortcuts.

---

## License

**Source Available License** — Free for educational and personal use.

| Use Case | Allowed | Cost |
|----------|---------|------|
| Learning / Education | ✅ | Free |
| Personal Projects | ✅ | Free |
| Academic Research | ✅ | Free |
| Portfolio | ✅ | Free |
| Commercial / Business | ⚠️ | [Contact](https://datascience-adventure.xyz/contact) |

See [LICENSE](LICENSE) for full terms.

---

**Built with:** Python · FastAPI · Flask · SQLAlchemy · Strawberry GraphQL · Chart.js · Aria Engine · LiteLLM · MLX · PostgreSQL · Docker · Traefik · Prometheus · Grafana
