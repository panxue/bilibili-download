#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

uv sync --quiet

exec uv run uvicorn backend.main:app --host "${BLDLP_HOST:-127.0.0.1}" --port "${BLDLP_PORT:-8000}"