#!/usr/bin/env bash
# scripts/backup_db.sh — Aria PostgreSQL backup with 7-day retention
# Usage: ./scripts/backup_db.sh
# Cron:  0 3 * * * /path/to/aria/scripts/backup_db.sh >> /tmp/aria-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${ARIA_BACKUP_DIR:-/Users/najia/aria/backups/db}"
RETENTION_DAYS=7
CONTAINER="aria-db"
DB_USER="${DB_USER:-admin}"
DB_NAME="${DB_NAME:-aria_warehouse}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/aria_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting backup of ${DB_NAME}..."

docker exec "$CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"

if [[ -s "$BACKUP_FILE" ]]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[$(date)] Backup complete: ${BACKUP_FILE} (${SIZE})"
else
    echo "[$(date)] ERROR: Backup file is empty or missing" >&2
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Prune backups older than retention period
DELETED=$(find "$BACKUP_DIR" -name "aria_*.sql.gz" -mtime +${RETENTION_DAYS} -print -delete | wc -l)
echo "[$(date)] Pruned ${DELETED} backups older than ${RETENTION_DAYS} days"
