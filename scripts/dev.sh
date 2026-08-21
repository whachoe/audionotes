#!/usr/bin/env bash
# Run the backend locally (no Docker) for development, with autoreload.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -d .venv ]]; then
  echo "ERROR: .venv not found at ${repo_root}/.venv. Create it first, e.g.:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

export API_TOKEN="${API_TOKEN:-dev-token}"
export DATA_DIR="${DATA_DIR:-./data}"

# --app-dir adds src/ to sys.path so `backend` resolves as a top-level
# package, matching pyproject.toml's pythonpath used for tests.
exec uvicorn backend.main:app --reload --app-dir src --host 127.0.0.1 --port 8000
