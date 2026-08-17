#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
exec python3 -m uvicorn server:app \
  --host "${RERANKER_ADAPTER_HOST:-127.0.0.1}" \
  --port "${RERANKER_ADAPTER_PORT:-7998}"
