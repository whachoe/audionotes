#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

git pull
sudo .venv/bin/pip install -r requirements.txt
sudo systemctl daemon-reload
sudo systemctl restart audionotes-backend

# Now go back to previous path
cd -
