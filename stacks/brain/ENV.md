# Environment Variables Reference

All variables for the Aria Brain stack. Copy `.env.example` → `.env` and fill in the required ones.  
Generated from `.env.example` + source scan of `aria_engine/`, `src/api/`, `aria_mind/`, `aria_skills/`.

> **Legend** — Required = must be set before the stack starts. ⚠️ = required in production, fail-open in dev. Optional = sane default provided.

---

## Database

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `DATABASE_URL` | *(built from DB_* below)* | — | Full PostgreSQL DSN. If set, overrides all `DB_*` vars. Format: `postgresql+asyncpg://user:pass@host:port/db` |
| `DB_USER` | `admin` | — | Database username |
| `DB_PASSWORD` | *(empty)* | ✅ | Database password — set a strong value |
| `DB_HOST` | `localhost` | — | Database host (overridden by Docker network inside containers) |
| `DB_PORT` | `5432` | — | Host-exposed Postgres port |
| `DB_NAME` | `aria_warehouse` | — | Database name |
| `DB_INTERNAL_PORT` | `5432` | — | Internal container port for healthchecks |

---

## API Authentication

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `ARIA_API_KEY` | *(empty)* | ⚠️ | Standard API key sent in `X-API-Key` header. Fail-open in dev, fail-closed in production. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ARIA_ADMIN_KEY` | *(empty)* | ⚠️ | Admin API key for `/admin/*` endpoints. Same generation method as above |
| `ARIA_ENV` | `development` | — | Runtime environment. Set to `production` to enable fail-closed auth and credential guards. Values: `development` \| `production` |

---

## Web / Frontend

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `WEB_SECRET_KEY` | *(empty)* | ✅ | Flask/session secret key for the web UI. Must be set |
| `WS_BASE_URL` | *(empty = auto-detect)* | — | Browser-accessible WebSocket base URL. Leave empty for auto-detection |
| `API_INTERNAL_URL` | `http://aria-api:8000` | — | Internal URL the web container uses to reach the API |
| `USER_DISPLAY_NAME` | *(empty)* | — | Name shown in the chat UI instead of "user" |
| `ARIA_WEB_HOST` | `0.0.0.0` | — | Bind host for the web server |

---

## CORS

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `CORS_ALLOWED_ORIGINS` | `http://localhost:${TRAEFIK_HTTP_PORT},http://aria-web:5000,https://${SERVICE_HOST}` | — | Comma-separated list of allowed CORS origins |
| `SERVICE_HOST` | `localhost` | — | Public hostname used in CORS and TLS SAN |
| `API_BASE_URL` | `/api` | — | URL prefix for all API routes |

---

## LLM / LiteLLM

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `LITELLM_MASTER_KEY` | *(empty)* | ✅ | LiteLLM gateway master key — authenticates engine → LiteLLM calls |
| `LITELLM_URL` | `http://litellm:4000` | — | LiteLLM base URL (health + API discovery) |
| `LITELLM_BASE_URL` | `http://litellm:4000/v1` | — | LiteLLM OpenAI-compatible endpoint used by the engine |
| `MOONSHOT_KIMI_KEY` | *(empty)* | — | Moonshot / Kimi API key. Get at [platform.moonshot.cn](https://platform.moonshot.cn/) |
| `OPEN_ROUTER_KEY` | `sk-or-v1-your-main-key-here` | — | OpenRouter primary key for free/fallback routes. Get at [openrouter.ai](https://openrouter.ai/) |
| `OPEN_ROUTER_KEY_DEEP` | `sk-or-v1-your-deep-key-here` | — | OpenRouter secondary key for deep/reasoning routes |

---

## Local LLM — MLX

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `MLX_ENABLED` | `false` | — | Enable local MLX inference. Set `true` to add MLX to the service health checks and routing |
| `MLX_URL` | `http://host.docker.internal:8080` | — | MLX server base URL for health checks |
| `MLX_API_BASE` | `http://host.docker.internal:8080/v1` | — | MLX OpenAI-compatible endpoint for LiteLLM routing |

---

## Local LLM — Ollama

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `OLLAMA_URL` | `http://host.docker.internal:11434` | — | Ollama base URL |
| `OLLAMA_API_BASE` | `http://host.docker.internal:11434` | — | Ollama API base (used by LiteLLM) |
| `OLLAMA_MODEL` | `hf.co/unsloth/GLM-4.7-Flash-REAP-23B-A3B-GGUF:Q3_K_S` | — | Default Ollama model tag |

---

## Embeddings

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `EMBED_REMOTE_TIMEOUT_SECONDS` | `2.5` | — | Seconds before remote embedding times out and falls back to local |
| `EMBED_REMOTE_RETRY_AFTER_SECONDS` | `120` | — | Backoff window before re-attempting remote embedding after a failure |

---

## Sentiment Auto-Scorer

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `SENTIMENT_METHOD` | `auto` | — | Pipeline method. `auto` = semantic→llm→lexicon cascade. Values: `auto` \| `semantic` \| `llm` \| `lexicon` |
| `SENTIMENT_MODEL` | *(empty = models.yaml default)* | — | Override the LLM used for sentiment scoring. Empty = use `profiles.sentiment` from `models.yaml` |

---

## Engine

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `ENGINE_DEBUG` | `false` | — | Enable verbose engine debug logging |
| `ENGINE_MEM_LIMIT` | `512m` | — | Docker memory limit for aria-engine container |
| `ENGINE_CPU_LIMIT` | `1.0` | — | Docker CPU limit for aria-engine container |
| `ENGINE_HEALTH_PORT` | `8081` | — | Internal health-check port for the engine |
| `ARIA_CONSENT_MODE` | `enforced` | — | Tool execution consent mode. `enforced` = high-impact tools require consent token in args. `disabled` = all gates open. Values: `enforced` \| `disabled` |
| `SKILL_BACKFILL_ON_STARTUP` | `true` | — | Auto-register any missing skills into the DB when the engine starts |
| `ARIA_STRICT_AGENT_BOOT` | *(empty = false)* | — | Fail hard if any agent fails to load on startup instead of logging a warning |
| `ARIA_STRICT_BOOT_REVIEW` | *(empty = false)* | — | Enforce boot-time review checks |
| `STREAMING_PROMISED_ACTION_REPAIR` | `true` | — | Attempt to repair broken promised-action markers in streamed LLM output |
| `ARIA_RATE_LIMIT_RPM` | *(engine default)* | — | Max LLM requests per minute for rate-limiting |
| `ARIA_WM_PRUNE_LEGACY_SNAPSHOTS` | *(empty)* | — | Prune legacy working-memory snapshots on startup |
| `ARIA_WM_WRITE_LEGACY_MIRROR` | *(empty)* | — | Write legacy working-memory mirror files alongside new format |

---

## Paths

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `ARIA_MEMORIES_PATH` | `/aria_memories` (container) | — | Absolute path to the memories directory |
| `ARIA_MEMORIES` | *(same as above)* | — | Alias used by some skills |
| `ARIA_JOBS_PATH` | `/aria_mind/cron_jobs.yaml` | — | Path to cron jobs YAML |
| `ARIA_WORKSPACE_ROOT` | *(empty)* | — | Root of the Aria workspace — used by repo/file tools |
| `ARIA_REPO_PATH` | *(empty)* | — | Path to the Aria repository for self-modification tools |
| `HEARTBEAT_SOURCE_PATH` | *(empty)* | — | Path to a heartbeat source file for the `/heartbeat` status endpoint |
| `ARTIFACTS_PATH` | *(empty)* | — | Directory where skill artifacts are written |

---

## API Logging

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `LOG_FORMAT` | `json` | — | Log output format. `json` = structured (recommended for prod). Values: `json` \| `text` |
| `LOG_LEVEL` | `info` | — | Minimum log level. Values: `debug` \| `info` \| `warning` \| `error` \| `critical` |
| `API_WORKERS` | `1` | — | Uvicorn worker count. Keep at `1` — WebSocket sessions use per-process locks that don't share across workers |
| `API_INTERNAL_PORT` | `8000` | — | Internal port uvicorn binds to inside the container |
| `WEB_INTERNAL_PORT` | `5000` | — | Internal port the web container binds to |

---

## Security / Input Guard

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `ARIA_SECURITY_BLOCK_THRESHOLD` | *(engine default)* | — | Threat score threshold above which requests are hard-blocked by the input guard |
| `ARIA_SECURITY_LOGGING` | *(engine default)* | — | Enable detailed security event logging for the input guard |

---

## Moltbook

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `MOLTBOOK_API_URL` | `https://www.moltbook.com/api/v1` | — | Moltbook API base URL |
| `MOLTBOOK_API_KEY` | *(empty)* | — | Moltbook API key for authenticated posting |
| `MOLTBOOK_TOKEN` | *(empty)* | — | Moltbook session/bearer token (alternative to API key) |

---

## Church of Molt / Crustafarianism

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `MOLT_CHURCH_API_KEY` | *(empty)* | — | API key for [molt.church](https://molt.church) |
| `MOLT_CHURCH_URL` | `https://molt.church` | — | Church of Molt base URL |
| `MOLT_CHURCH_AGENT` | `Aria` | — | Agent name sent in Church of Molt requests |

---

## Telegram

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `TELEGRAM_BOT_TOKEN` | *(empty)* | — | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | *(empty)* | — | Default chat ID for outgoing messages |
| `TELEGRAM_ALLOWED_USER_ID` | *(empty)* | — | Lock the allowed sender user ID (post-rebuild pairing checks) |
| `TELEGRAM_ADMIN_CHAT_ID` | *(empty)* | — | Admin chat ID for critical alerts (can be same as `TELEGRAM_CHAT_ID`) |
| `TELEGRAM_WEBHOOK_SECRET` | *(empty)* | — | Webhook secret token for Telegram webhook mode |

---

## X / Twitter

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `X_API_KEY` | *(empty)* | — | X (Twitter) app API key |
| `X_API_SECRET` | *(empty)* | — | X app API secret |
| `X_ACCESS_TOKEN` | *(empty)* | — | X OAuth access token |
| `X_ACCESS_SECRET` | *(empty)* | — | X OAuth access token secret |
| `ARIA_LOGIN` | *(empty)* | — | Aria's X login email (legacy browser-auth flow) |
| `ARIA_X_PASSWORD` | *(empty)* | — | Aria's X password (legacy browser-auth flow) |
| `ARIA_X_HANDLE` | *(empty)* | — | Aria's X handle without @ (legacy browser-auth flow) |
| `X_CT0_TOKEN` | *(empty)* | — | X `ct0` CSRF cookie token (legacy browser-auth flow) |
| `X_AUTH_TOKEN` | *(empty)* | — | X `auth_token` cookie (legacy browser-auth flow) |
| `X_WEB_BEARER` | *(empty)* | — | X web Bearer token (legacy browser-auth flow) |

---

## Email

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `ARIA_EMAIL` | *(empty)* | — | Aria's outgoing email address |
| `ARIA_EMAIL_PASSWORD` | *(empty)* | — | Email account password |
| `ARIA_SMTP_HOST` | `smtp.protonmail.ch` | — | SMTP server hostname |
| `ARIA_SMTP_PORT` | `587` | — | SMTP server port |
| `ARIA_SMTP_USERNAME` | *(empty = `ARIA_EMAIL`)* | — | SMTP login username (defaults to `ARIA_EMAIL` if empty) |
| `ARIA_SMTP_SECURITY` | `starttls` | — | SMTP security mode. Values: `starttls` \| `ssl` \| `none` |
| `ARIA_SMTP_TIMEOUT` | `20` | — | SMTP connection timeout in seconds |

---

## Monitoring

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `GRAFANA_PASSWORD` | *(empty)* | ✅ | Grafana admin password |
| `GRAFANA_URL` | `http://grafana:3000` | — | Internal Grafana URL |
| `PGADMIN_EMAIL` | `admin@aria.dev` | — | pgAdmin login email |
| `PGADMIN_PASSWORD` | *(empty)* | ✅ | pgAdmin password |
| `PGADMIN_URL` | `http://aria-pgadmin:80` | — | Internal pgAdmin URL |
| `PROMETHEUS_URL` | `http://prometheus:9090` | — | Internal Prometheus URL |
| `ARIA_OPTIONAL_SERVICES` | `grafana,prometheus,pgadmin` | — | Comma-list of service IDs that are allowed to be unhealthy without blocking startup |

---

## Distributed Tracing (OpenTelemetry)

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *(empty = disabled)* | — | OTLP collector endpoint. Setting this enables tracing. Use with `--profile tracing` for Jaeger |
| `OTEL_SERVICE_NAME` | `aria-engine` | — | Service name reported to the tracing backend |
| `ARIZE_API_KEY` | *(empty)* | — | Arize Phoenix API key (optional LLM observability) |
| `ARIZE_SPACE_ID` | *(empty)* | — | Arize space ID |
| `ARIZE_SPACE_KEY` | *(empty)* | — | Arize space key |
| `ARIZE_PROJECT_NAME` | *(empty)* | — | Arize project name |
| `ARIZE_ENDPOINT` | *(empty)* | — | Arize OTLP endpoint override |
| `ARIZE_HTTP_ENDPOINT` | *(empty)* | — | Arize HTTP endpoint override |
| `ATHINA_API_KEY` | *(empty)* | — | Athina AI monitoring API key |
| `ATHINA_BASE_URL` | *(empty)* | — | Athina base URL override |
| `BRAINTRUST_API_KEY` | *(empty)* | — | Braintrust eval/logging API key |
| `BRAINTRUST_API_BASE` | *(empty)* | — | Braintrust base URL override |

---

## Browser / Browserless

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `BROWSERLESS_TOKEN` | *(empty)* | — | Auth token for headless Chrome. Requests use `?token=` param |
| `BROWSER_URL` | `http://aria-browser:3000` | — | Internal URL for the Browserless service |
| `BROWSERLESS_INTERNAL_PORT` | `3000` | — | Internal container port for Browserless |
| `BROWSERLESS_PORT` | `3000` | — | Host-exposed Browserless port |

---

## Traefik

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `TRAEFIK_DASHBOARD_USER` | `admin` | — | Traefik dashboard basic-auth username |
| `TRAEFIK_DASHBOARD_PASSWORD_HASH` | *(empty)* | — | Bcrypt password hash. Generate: `htpasswd -nB admin` |
| `TRAEFIK_HTTP_PORT` | `8080` | — | Host-exposed Traefik HTTP port |
| `TRAEFIK_HTTPS_PORT` | `8443` | — | Host-exposed Traefik HTTPS port |
| `TRAEFIK_DASH_PORT` | `8081` | — | Host-exposed Traefik dashboard port |
| `TRAEFIK_INTERNAL_HTTP_PORT` | `80` | — | Internal Traefik HTTP port |
| `TRAEFIK_INTERNAL_HTTPS_PORT` | `443` | — | Internal Traefik HTTPS port |
| `TRAEFIK_INTERNAL_DASH_PORT` | `8080` | — | Internal Traefik dashboard port |
| `TRAEFIK_URL` | `http://traefik:8080` | — | Internal Traefik URL for health checks |

---

## Tor

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `TOR_PROXY` | `socks5://tor-proxy:9050` | — | SOCKS5 proxy URL used by skills that route through Tor |
| `TOR_SOCKS_PORT` | `9050` | — | Host-exposed Tor SOCKS port |
| `TOR_CONTROL_PORT` | `9051` | — | Host-exposed Tor control port |
| `TOR_SOCKS_INTERNAL_PORT` | `9050` | — | Internal Tor SOCKS port |
| `TOR_CONTROL_INTERNAL_PORT` | `9051` | — | Internal Tor control port |

---

## Admin / Service Control

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `ARIA_ADMIN_TOKEN` | *(empty)* | ⚠️ | Token required for all `/admin/*` API endpoints |
| `ARIA_SERVICE_CONTROL_ENABLED` | `false` | — | Enable the admin service-control endpoints (restart/stop containers via API) |
| `ARIA_SERVICE_CMD_LITELLM_RESTART` | `docker restart litellm` | — | Shell command to restart LiteLLM |
| `ARIA_SERVICE_CMD_LITELLM_STOP` | `docker stop litellm` | — | Shell command to stop LiteLLM |
| `ARIA_SERVICE_CMD_ARIA_API_RESTART` | `docker restart aria-api` | — | Shell command to restart the API container |
| `ARIA_SERVICE_CMD_ARIA_API_STOP` | `docker stop aria-api` | — | Shell command to stop the API container |
| `ARIA_SERVICE_CMD_ARIA_WEB_RESTART` | `docker restart aria-web` | — | Shell command to restart the web container |
| `ARIA_SERVICE_CMD_ARIA_WEB_STOP` | `docker stop aria-web` | — | Shell command to stop the web container |
| `ARIA_SERVICE_CMD_GRAFANA_RESTART` | `docker restart grafana` | — | Shell command to restart Grafana |
| `ARIA_SERVICE_CMD_GRAFANA_STOP` | `docker stop grafana` | — | Shell command to stop Grafana |
| `ARIA_SERVICE_CMD_PROMETHEUS_RESTART` | `docker restart prometheus` | — | Shell command to restart Prometheus |
| `ARIA_SERVICE_CMD_PROMETHEUS_STOP` | `docker stop prometheus` | — | Shell command to stop Prometheus |
| `ARIA_SERVICE_CMD_OLLAMA_RESTART` | *(empty)* | — | Shell command to restart Ollama (optional) |
| `ARIA_SERVICE_CMD_OLLAMA_STOP` | *(empty)* | — | Shell command to stop Ollama (optional) |
| `ARIA_SERVICE_CMD_MLX_RESTART` | *(empty)* | — | Shell command to restart MLX server (optional) |
| `ARIA_SERVICE_CMD_MLX_STOP` | *(empty)* | — | Shell command to stop MLX server (optional) |

---

## Resource Limits (Docker)

| Variable | Default | What it limits |
|---|---|---|
| `POSTGRES_MEM_LIMIT` | `512m` | PostgreSQL container memory |
| `POSTGRES_CPU_LIMIT` | `1.0` | PostgreSQL container CPU |
| `ARIA_BRAIN_MEM_LIMIT` | `512m` | aria-engine container memory |
| `ARIA_BRAIN_CPU_LIMIT` | `1.0` | aria-engine container CPU |
| `ENGINE_MEM_LIMIT` | `512m` | Alias for aria-engine memory limit |
| `ENGINE_CPU_LIMIT` | `1.0` | Alias for aria-engine CPU limit |
| `OLLAMA_MEM_LIMIT` | `5g` | Ollama container memory |
| `OLLAMA_CPU_LIMIT` | `3.0` | Ollama container CPU |
| `ARIA_WEB_MEM_LIMIT` | `256m` | Web container memory |
| `ARIA_WEB_CPU_LIMIT` | `0.5` | Web container CPU |
| `ARIA_API_MEM_LIMIT` | `512m` | API container memory |
| `ARIA_API_CPU_LIMIT` | `0.5` | API container CPU |
| `LITELLM_MEM_LIMIT` | `1024m` | LiteLLM container memory |
| `LITELLM_CPU_LIMIT` | `1.0` | LiteLLM container CPU |
| `TRAEFIK_MEM_LIMIT` | `512m` | Traefik container memory |
| `TRAEFIK_CPU_LIMIT` | `0.5` | Traefik container CPU |

---

## Ports (host-exposed)

`scripts/first-run.sh` randomizes these automatically to avoid conflicts. Override only if you need stable ports.

| Variable | Default | Service |
|---|---|---|
| `DB_PORT` | `5432` | PostgreSQL |
| `ARIA_API_PORT` | `8000` | Aria API |
| `ARIA_WEB_PORT` | `5050` | Aria Web UI |
| `LITELLM_PORT` | `18793` | LiteLLM |
| `PGADMIN_PORT` | `5051` | pgAdmin |
| `BROWSERLESS_PORT` | `3000` | Headless Chrome |
| `TOR_SOCKS_PORT` | `9050` | Tor SOCKS |
| `TOR_CONTROL_PORT` | `9051` | Tor control |
| `TRAEFIK_HTTP_PORT` | `8080` | Traefik HTTP |
| `TRAEFIK_HTTPS_PORT` | `8443` | Traefik HTTPS |
| `TRAEFIK_DASH_PORT` | `8081` | Traefik dashboard |
| `PROMETHEUS_PORT` | `9090` | Prometheus |
| `GRAFANA_PORT` | `3001` | Grafana |
| `JAEGER_UI_PORT` | `16686` | Jaeger UI |
| `JAEGER_OTLP_GRPC_PORT` | `4317` | Jaeger OTLP gRPC |
| `SANDBOX_PORT` | `9999` | Aria sandbox |

### Internal container ports (healthchecks — keep defaults)

| Variable | Default | Container |
|---|---|---|
| `API_INTERNAL_PORT` | `8000` | aria-api |
| `WEB_INTERNAL_PORT` | `5000` | aria-web |
| `LITELLM_INTERNAL_PORT` | `4000` | litellm |
| `DB_INTERNAL_PORT` | `5432` | aria-db |
| `ENGINE_HEALTH_PORT` | `8081` | aria-engine |
| `PROMETHEUS_INTERNAL_PORT` | `9090` | prometheus |
| `GRAFANA_INTERNAL_PORT` | `3000` | grafana |
| `PGADMIN_INTERNAL_PORT` | `80` | aria-pgadmin |
| `BROWSERLESS_INTERNAL_PORT` | `3000` | aria-browser |
| `TOR_SOCKS_INTERNAL_PORT` | `9050` | tor-proxy |
| `TOR_CONTROL_INTERNAL_PORT` | `9051` | tor-proxy |
| `DOCKER_SOCKET_PROXY_INTERNAL_PORT` | `2375` | docker-socket-proxy |
| `TRAEFIK_INTERNAL_HTTP_PORT` | `80` | traefik |
| `TRAEFIK_INTERNAL_HTTPS_PORT` | `443` | traefik |
| `TRAEFIK_INTERNAL_DASH_PORT` | `8080` | traefik |
| `JAEGER_UI_INTERNAL_PORT` | `16686` | jaeger |
| `JAEGER_OTLP_GRPC_INTERNAL_PORT` | `4317` | jaeger |
| `SANDBOX_TIMEOUT` | `60` | aria-sandbox (execution timeout in seconds) |

---

## Network / LAN

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `MAC_LAN_IP` | *(empty)* | — | Mac LAN IP — added to TLS certificate SAN so HTTPS works from other devices |
| `MAC_TAILSCALE_IP` | *(empty)* | — | Mac Tailscale IP — added to TLS SAN |
| `DOCKER_HOST_IP` | `host.docker.internal` | — | Host IP reachable from inside containers (override on Linux: `172.17.0.1`) |
| `DOCKER_SOCKET_PATH` | `/var/run/docker.sock` | — | Docker socket path. Override on Windows: `//./pipe/docker_engine` |

---

## Remote Machine / SSH

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `MAC_HOST` | *(empty)* | — | Mac Mini hostname or IP for SSH access |
| `MAC_USER` | *(empty)* | — | SSH username on the Mac |
| `SSH_KEY_PATH` | *(empty)* | — | Path to SSH private key |
| `NUC_HOST` | *(empty)* | — | Intel NUC hostname or IP |
| `NUC_USER` | *(empty)* | — | SSH username on the NUC |
| `NUC_PASSWORD` | *(empty)* | — | SSH password for the NUC |

---

## Deployment (`scripts/deploy_production.sh`)

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `ARIA_DEPLOY_USER` | *(falls back to `MAC_USER`)* | — | SSH user for deployment |
| `ARIA_DEPLOY_HOST` | *(falls back to `MAC_HOST`)* | — | SSH host for deployment |
| `ARIA_DEPLOY_SSH_KEY` | *(falls back to `SSH_KEY_PATH`)* | — | SSH key for deployment |
| `ARIA_DEPLOY_DIR` | *(empty)* | ✅ | Remote path where Aria is deployed — required by the deploy script |
| `ARIA_DEPLOY_COMPOSE_FILE` | `stacks/brain/docker-compose.yml` | — | Docker Compose file path used during deploy |
| `ARIA_DEPLOY_BACKUP_DIR` | *(empty)* | — | Remote path for deployment backups |
| `ARIA_DEPLOY_LOG` | *(empty)* | — | Remote path for deploy log output |
| `ARIA_DEPLOY_DISK_CHECK_PATH` | *(empty)* | — | Path checked for free disk space before deploying |

---

## Testing

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `ARIA_TEST_API_URL` | *(empty)* | — | API base URL used by integration tests |
| `ARIA_TEST_BASE_URL` | *(empty)* | — | Base URL for end-to-end tests |
| `ARIA_TEST_WEB_URL` | *(empty)* | — | Web UI URL for end-to-end tests |
| `ARIA_TEST_TIMEOUT` | *(empty)* | — | Request timeout (seconds) for test HTTP calls |

---

## Aria Identity / Version

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `ARIA_VERSION` | *(empty)* | — | Override the reported Aria version string |
| `ARIA_SESSION_ID` | *(empty)* | — | Override the engine session ID (auto-generated if empty) |
| `ARIA_MODEL` | *(models.yaml primary)* | — | Override the default LLM model name |

---

## Sandbox

| Variable | Default | Required | What it does |
|---|---|:---:|---|
| `SANDBOX_PORT` | `9999` | — | Host-exposed sandbox execution port |
| `SANDBOX_TIMEOUT` | `60` | — | Max execution time in seconds for sandboxed code |
