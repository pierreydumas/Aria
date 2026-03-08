# Aria Production Runbook

## Quick Commands
- Start stack: `docker compose -f stacks/brain/docker-compose.yml up -d`
- Stop stack: `docker compose -f stacks/brain/docker-compose.yml down`
- Tail logs: `docker compose -f stacks/brain/docker-compose.yml logs -f --tail=100`
- Verify deployment: `./tests/e2e/verify_deployment.sh`
- Apply patch: `./scripts/apply_patch.sh <patch_dir>`

## Service Recovery
- Restart API: `docker restart aria-api`
- Restart web: `docker restart aria-web`
- Restart brain: `docker restart aria-brain`
- Full restart: `docker compose -f stacks/brain/docker-compose.yml restart`

## Health Monitoring
- API health: `curl -s http://localhost:8000/health`
- Web health: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5000/`
- Watchdog run: `./scripts/health_watchdog.sh aria-api`
- Watchdog state/log: `aria_memories/logs/health_watchdog.state`, `aria_memories/logs/health_watchdog.log`

## Rollback Procedure
1. Use latest backup from `aria_memories/exports/patch_backup_*`.
2. Restore files: `rsync -a <backup_dir>/ ./`
3. Restart containers: `docker compose -f stacks/brain/docker-compose.yml restart aria-api aria-web aria-brain`
4. Re-run `./tests/e2e/verify_deployment.sh --quick`.

## Incident Notes
- Keep all runtime logs and alerts in `aria_memories/logs/`.
- Do not store credentials in repo files; use environment variables only.
- Keep writes limited to `aria_memories/` for Aria-generated artifacts.
