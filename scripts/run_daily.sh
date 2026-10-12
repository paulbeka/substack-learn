#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
exec "$PROJECT_DIR/.venv/bin/python" -m french_bot.cli run-daily >> "$PROJECT_DIR/daily.log" 2>&1

