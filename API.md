# Aria Blue ⚡️ — API & Dashboard

## API — FastAPI v3.0

Aria's backend is a FastAPI application with async SQLAlchemy 2.0 ORM, psycopg 3 driver, and Strawberry GraphQL.

The API is the **sole database gateway** — all skills and agents access data through it, never directly.

### REST Routers

All routers live in `src/api/routers/` — 36 router files containing 240+ REST endpoints, 2 WebSocket endpoints, and 1 GraphQL schema.

**→ [`src/api/routers/`](src/api/routers/)**

Key endpoints:

| Prefix | Purpose |
|--------|---------|
| `/health`, `/status`, `/stats` | Liveness, readiness, service status |
| `/activities` | Activity log CRUD + stats |
| `/goals`, `/hourly-goals` | Goal tracking + micro-goals |
| `/working-memory` | Working memory CRUD, context ranking, checkpointing |
| `/knowledge-graph` | Knowledge graph entities + relations |
| `/model-usage` | LLM usage metrics + cost tracking |
| `/security-events` | Security audit log + threat detection |
| `/agents/db` | Agent CRUD — create, update, enable/disable, delete, sync from AGENTS.md |
| `/models/db` | LLM model CRUD — create, update, delete, sync from models.yaml |
| `/models/available` | Active models for chat UI model selector |
| `/engine/chat` | Engine chat sessions — create, message, export, history |
| `/engine/cron` | Cron job management — CRUD + trigger + history |
| `/engine/agents` | Engine agent state + performance metrics |
| `/engine/roundtable` | Multi-agent roundtable discussions + swarm decisions |
| `/artifacts` | File artifact CRUD in aria_memories/ |
| `/rpg/campaigns` | RPG campaign dashboard, sessions, knowledge graph |

**Totals:** 36 router files, 240+ REST endpoints, 2 WebSocket endpoints, 1 GraphQL endpoint.

Full interactive docs are served at `/api/docs` (Swagger) when the stack is running.

### GraphQL

Strawberry GraphQL schema at `/graphql` — query activities, thoughts, memories, goals with filtering and pagination.

Source: `src/api/gql/`

### Security Middleware

- Per-IP rate limiting
- Prompt injection scanning
- SQL/XSS/path traversal detection
- Security headers on all responses

Source: `src/api/security_middleware.py`

### Database ORM

SQLAlchemy 2.0 async models and session management:

- Models: `src/api/db/models.py` — 39 ORM models across two schemas (`aria_data`, `aria_engine`)
- Session: `src/api/db/session.py` — auto-creates both schemas on startup
- Documentation: `src/api/db/MODELS.md`
- Migrations: `src/api/alembic/`

---

## Dashboard — Flask + Chart.js

A Flask application with 43 Jinja2 templates, Chart.js visualizations, tabbed layouts, and auto-refresh.

The Flask app includes a reverse proxy for seamless `/api/*` forwarding.

### Source

- App: `src/web/app.py`
- Templates: `src/web/templates/` (43 pages)
- Static assets: `src/web/static/`

### Key Pages

| Page | Features |
|------|----------|
| Dashboard | Overview stats, service status, host metrics |
| Models | LLM routing, wallets, spend tracking |
| Sessions | Agent sessions with cron toggle |
| Goals | Main goals + hourly goals, progress charts |
| Skills | Skill registry with status overview |
| Operations | Cron jobs, scheduled tasks, heartbeat |
| Security | Threat detection, security events |
| Working Memory | DB context + checkpoint management + file snapshot |
| Knowledge | Knowledge graph entities + relations |
| Soul | Soul documents + file browsers (`aria_mind/`, `aria_memories/`) |

Browse `src/web/templates/*.html` for the full list.

---

## Related

- [ARCHITECTURE.md](ARCHITECTURE.md) — System design and data flow
- [AUDIT_REPORT.md](docs/archive/AUDIT_REPORT.md) — Per-page web audit with API call analysis
- [DEPLOYMENT.md](DEPLOYMENT.md) — Service URLs and how to access
