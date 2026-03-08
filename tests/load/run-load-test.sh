#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Aria — Locust load-test runner  (S-30)
#
# Usage:
#   ./tests/load/run-load-test.sh                 # default: 10 users, 1/s ramp
#   USERS=100 RATE=5 DURATION=5m ./tests/load/run-load-test.sh
#
# Environment variables:
#   USERS      – peak concurrent users    (default: 10)
#   RATE       – users spawned per second  (default: 1)
#   DURATION   – test duration             (default: 2m)
#   HOST       – target base URL           (default: http://localhost:5050)
#   TAGS       – only run tasks with tags  (default: all)
#   REPORT_DIR – output directory          (default: tests/load)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

USERS="${USERS:-10}"
RATE="${RATE:-1}"
DURATION="${DURATION:-2m}"
HOST="${HOST:-http://localhost:5050}"
REPORT_DIR="${REPORT_DIR:-$ROOT_DIR/tests/load}"
TAGS="${TAGS:-}"

LOCUSTFILE="$ROOT_DIR/tests/load/locustfile.py"
REPORT_HTML="$REPORT_DIR/report.html"
REPORT_CSV="$REPORT_DIR/report"

# ── Pre-flight checks ────────────────────────────────────────────────────────

if ! command -v locust &>/dev/null; then
    echo "⚙️  Installing locust …"
    pip install --quiet "locust>=2.29"
fi

# Ensure the target is reachable
echo "🔍 Checking $HOST/health …"
if ! curl -sf --max-time 5 "$HOST/health" > /dev/null 2>&1; then
    echo "⚠️  $HOST/health unreachable — make sure the stack is running"
    echo "   e.g.  docker compose -f stacks/brain/docker-compose.yml up -d"
    exit 1
fi

mkdir -p "$REPORT_DIR"

# ── Run ───────────────────────────────────────────────────────────────────────

EXTRA_ARGS=()
if [[ -n "$TAGS" ]]; then
    EXTRA_ARGS+=(--tags "$TAGS")
fi

echo ""
echo "🚀 Running Locust load test"
echo "   Users:    $USERS"
echo "   Rate:     $RATE/s"
echo "   Duration: $DURATION"
echo "   Host:     $HOST"
echo "   Tags:     ${TAGS:-all}"
echo ""

locust \
    -f "$LOCUSTFILE" \
    --headless \
    --host "$HOST" \
    --users "$USERS" \
    --spawn-rate "$RATE" \
    --run-time "$DURATION" \
    --html "$REPORT_HTML" \
    --csv "$REPORT_CSV" \
    "${EXTRA_ARGS[@]}"

echo ""
echo "✅ Load test complete"
echo "   HTML report: $REPORT_HTML"
echo "   CSV files:   ${REPORT_CSV}_*.csv"
