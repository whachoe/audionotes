#!/usr/bin/env bash
# Tar up the data directory (audio files, markdown notes, sqlite db) into a
# timestamped archive.
#
# Usage:
#   scripts/backup.sh [DATA_DIR] [BACKUP_DIR]
# or via env vars:
#   DATA_DIR=./deploy/data BACKUP_DIR=./backups scripts/backup.sh
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

data_dir="${1:-${DATA_DIR:-${repo_root}/deploy/data}}"
backup_dir="${2:-${BACKUP_DIR:-${repo_root}/backups}}"

if [[ ! -d "$data_dir" ]]; then
  echo "ERROR: data directory not found: ${data_dir}" >&2
  exit 1
fi

mkdir -p "$backup_dir"

data_dir="$(cd "$data_dir" && pwd)"
timestamp="$(date +%Y%m%d-%H%M%S)"
archive="${backup_dir}/notes-backup-${timestamp}.tar.gz"

tar -czf "$archive" -C "$(dirname "$data_dir")" "$(basename "$data_dir")"

echo "Backup written to ${archive}"
