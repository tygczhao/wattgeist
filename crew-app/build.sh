#!/usr/bin/env bash
# Copy the WattGeist backend into the Crew app folder so the app is self-contained (Crew installs only the app folder).
# Only sources, pyproject and the lock file are copied, no virtualenv or caches; uv builds the environment from the lock on first run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${ROOT}/crew-app/wattgeist-night-watch"
rm -rf "${APP}/backend"
mkdir -p "${APP}/backend"
cp "${ROOT}/backend/pyproject.toml" "${ROOT}/backend/uv.lock" "${ROOT}/backend/.python-version" "${APP}/backend/"
cp -r "${ROOT}/backend/src" "${APP}/backend/src"
find "${APP}/backend" -name __pycache__ -type d -prune -exec rm -rf {} +
# Icon: rendered from the frontend favicon (needs Chrome; keeps the existing icon otherwise)
if [[ ! -f "${APP}/assets/icon.png" ]]; then
  echo "assets/icon.png missing: run scripts/make_icon.py" >&2
fi
echo "Bundled backend into ${APP}/backend"
