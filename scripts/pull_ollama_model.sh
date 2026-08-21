#!/usr/bin/env bash
# Pull the configured Ollama model into the running `ollama` compose service.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

docker compose -f deploy/docker-compose.yml exec ollama ollama pull "${OLLAMA_MODEL:-llama3.2:3b}"
