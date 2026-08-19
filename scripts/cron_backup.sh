#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi
mkdir -p logs
python scripts/backup.py >> logs/backup.log 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Backup failed with exit code $EXIT_CODE" >> logs/backup.log
fi
exit $EXIT_CODE
