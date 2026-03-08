#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

if git diff --cached --name-only | grep -E '^(aria_memories/|aria_mind/aria_memories/|aria_mind/skills/aria_memories/)' >/dev/null; then
	echo "Blocked commit: staged files include aria_memories data paths."
	echo "Unstage them before committing."
	exit 1
fi

python3 tests/check_architecture.py
