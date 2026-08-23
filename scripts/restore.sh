#!/usr/bin/env bash
# Usage: ./scripts/restore.sh /absolute/path/to/backup-directory
set -euo pipefail
backup_input=${1:?バックアップディレクトリを指定してください}
[[ "$backup_input" = /* ]] || { echo '絶対パスを指定してください。' >&2; exit 1; }
[[ -d "$backup_input" ]] || { echo 'バックアップディレクトリがありません。' >&2; exit 1; }
backup_dir=$(cd "$backup_input" && pwd -P)
[[ -d "$backup_dir" && -f "$backup_dir/db.sqlite3" ]] || { echo '有効なバックアップ（db.sqlite3を含むディレクトリ）を指定してください。' >&2; exit 1; }

docker compose stop app backup
trap 'docker compose up -d app backup >/dev/null 2>&1 || true' EXIT
# docker compose run resolves this project's app_runtime volume from this exact
# compose file; it never guesses from globally named Docker volumes.
docker compose run --rm --no-deps -v "$backup_dir:/backup:ro" app sh -ec '
  test -f /backup/db.sqlite3
  cp /backup/db.sqlite3 /app/runtime/db.sqlite3
  rm -rf /app/runtime/csv
  if [ -d /backup/csv ]; then cp -a /backup/csv /app/runtime/csv; fi
'
docker compose up -d app backup
trap - EXIT
echo '復元しました。'
