#!/usr/bin/env bash
# How + Path B at :8765, Path A at :5173, API at :8000. Ctrl-C stops all three.
set -euo pipefail
cd "$(dirname "$0")"

PIDS=()
stop() {
  trap - INT TERM EXIT
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap stop INT TERM EXIT

if [[ ! -d user_profile/frontend/node_modules ]]; then
  echo "Installing frontend dependencies…"
  npm --prefix user_profile/frontend install
fi

echo
echo "  How + Path B  ->  http://127.0.0.1:8765"
echo "  Path A        ->  http://127.0.0.1:5173"
echo "  API           ->  http://127.0.0.1:8000/docs"
echo "  Ctrl-C to stop"
echo

uv run uvicorn mandatelab_api:app --reload --host 127.0.0.1 --port 8000 \
  > >(sed -u 's/^/[api] /') 2>&1 &
PIDS+=($!)

npm --prefix user_profile/frontend run dev \
  > >(sed -u 's/^/[vite] /') 2>&1 &
PIDS+=($!)

uv run python buyer_history/examples/weekly_basket_app.py \
  > >(sed -u 's/^/[basket] /') 2>&1 &
PIDS+=($!)

wait
