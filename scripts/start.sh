#!/bin/sh
set -eu
python -m scripts.migrate
if [ "${LOAD_SAMPLE_DATA:-false}" = "true" ]; then
  python -m scripts.load_sample_data --once
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
