#!/bin/sh
set -eu
python -m scripts.migrate

# Open the API port before the first sample import, which can take several minutes.
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
api_pid=$!
# Stop the API if loading fails or Render stops this container.
trap 'kill "$api_pid" 2>/dev/null || true' EXIT
trap 'exit 143' TERM INT

if [ "${LOAD_SAMPLE_DATA:-false}" = "true" ]; then
  python -m scripts.load_sample_data --once
fi
wait "$api_pid"
