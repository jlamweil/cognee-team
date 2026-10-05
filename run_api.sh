#!/usr/bin/env bash
# Start the cognee team API server.
#
#   ./run_api.sh                          # foreground (systemd uses this too)
#   COGNEE_BIND=127.0.0.1 ./run_api.sh    # loopback only (default 0.0.0.0 = LAN)
#
# cwd MUST be cognee-team/ so cognee loads ./.env (security posture, data dir,
# LLM preset). Auth is always required; multi-tenant isolation always on.
set -euo pipefail
cd "$(dirname "$0")"

exec .venv/bin/python -m uvicorn cognee.api.client:app \
  --host "${COGNEE_BIND:-0.0.0.0}" \
  --port "${COGNEE_PORT:-8000}"
