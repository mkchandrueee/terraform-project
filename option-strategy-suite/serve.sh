#!/usr/bin/env bash
# Serve the suite locally. No build step — it just needs a static file server,
# because opening index.html over file:// blocks localStorage in some browsers
# and disables notifications entirely.
#
#   ./serve.sh          → http://127.0.0.1:8787
#   ./serve.sh 3000     → http://127.0.0.1:3000
#   HOST=0.0.0.0 ./serve.sh   → also reachable from your phone on the same wifi

set -euo pipefail

PORT="${1:-8787}"
HOST="${HOST:-127.0.0.1}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$ROOT"

echo "NIFTY Option Strategy Suite"
echo "  serving $ROOT"
echo "  http://${HOST}:${PORT}"
if [ "$HOST" = "0.0.0.0" ]; then
  echo "  (on your network: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT})"
fi
echo "  ctrl-c to stop"
echo

if command -v python3 >/dev/null 2>&1; then
  exec python3 -m http.server "$PORT" --bind "$HOST"
elif command -v npx >/dev/null 2>&1; then
  exec npx --yes serve --listen "tcp://${HOST}:${PORT}" .
elif command -v php >/dev/null 2>&1; then
  exec php -S "${HOST}:${PORT}"
else
  echo "Need python3, npx or php on PATH to serve static files." >&2
  exit 1
fi
