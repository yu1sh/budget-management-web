#!/usr/bin/env bash
# Run this on the server after cloning. It deliberately never stores the password.
set -euo pipefail
if [[ -f .env ]]; then echo '.env already exists; refusing to overwrite it.' >&2; exit 1; fi
command -v docker >/dev/null || { echo 'Docker が必要です。' >&2; exit 1; }
read -r -p '公開するドメイン (例: budget.example.com): ' SITE_DOMAIN
[[ "$SITE_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || { echo 'ドメイン形式が正しくありません。' >&2; exit 1; }
SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')
umask 077
printf 'DOMAIN=%s\nALLOWED_HOSTS=%s,localhost,127.0.0.1\nCSRF_TRUSTED_ORIGINS=https://%s\nDJANGO_SECRET_KEY=%s\nDEBUG=0\nSECURE_SSL_REDIRECT=1\n' "$SITE_DOMAIN" "$SITE_DOMAIN" "$SITE_DOMAIN" "$SECRET" > .env
chmod 600 .env
docker compose build
docker compose run --rm app python manage.py migrate --noinput
echo '管理者を作成します（パスワードは表示・保存・ログ出力されません）。'
docker compose run --rm app python manage.py bootstrap_admin
docker compose up -d
echo "起動しました: https://${SITE_DOMAIN}"
