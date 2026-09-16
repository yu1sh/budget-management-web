#!/usr/bin/env bash
# Root-only SSH deployment entry point. It receives a git archive on stdin.
set -Eeuo pipefail

readonly expected_path=/srv/apps/budget-management-web
readonly project=budget-management-web
readonly runtime_volume=budget-management-web_app_runtime
readonly releases="$expected_path/releases"
readonly overrides="$expected_path/.cd-overrides"
readonly backup_root=/srv/backups/budget-management-web-cd

fail() {
  printf 'Deployment refused: %s\n' "$*" >&2
  exit 1
}

if (( EUID != 0 )); then
  fail "must run as root"
fi
if (( $# != 2 )); then
  fail "expected commit SHA and deployment path"
fi
deploy_sha=$1
deploy_path=$2
if [[ ! "$deploy_sha" =~ ^[0-9a-f]{40}$ ]]; then
  fail "invalid commit SHA"
fi
if [[ "$deploy_path" != "$expected_path" ]]; then
  fail "deployment path does not match the production path"
fi

[[ -d "$expected_path" && ! -L "$expected_path" ]] || fail "production directory is missing or unsafe"
[[ -f "$expected_path/docker-compose.yml" && ! -L "$expected_path/docker-compose.yml" ]] || fail "existing Compose file is missing or unsafe"
[[ -f "$expected_path/.env" && ! -L "$expected_path/.env" ]] || fail "existing production .env file is missing or unsafe"

for volume in \
  "$runtime_volume" \
  budget-management-web_caddy_data \
  budget-management-web_caddy_config; do
  if ! docker volume inspect "$volume" >/dev/null 2>&1; then
    fail "required existing Docker volume $volume is missing"
  fi
  volume_project=$(docker volume inspect -f '{{ index .Labels "com.docker.compose.project" }}' "$volume")
  [[ "$volume_project" == "$project" ]] || fail "Docker volume $volume belongs to another Compose project"
done

install -d -o root -g root -m 0755 "$releases" "$overrides"
install -d -o root -g root -m 0700 "$backup_root"
[[ ! -L "$releases" && ! -L "$overrides" && ! -L "$backup_root" ]] || fail "deployment or backup directory is a symlink"

previous_release=$expected_path
if [[ -L "$expected_path/.cd-current" ]]; then
  previous_release=$(readlink -f -- "$expected_path/.cd-current") || fail "current release link is broken"
  [[ "$previous_release" == "$releases/"* && -d "$previous_release" ]] || fail "current release link points outside the release directory"
  previous_sha=${previous_release##*/}
  [[ "$previous_sha" =~ ^[0-9a-f]{40}$ ]] || fail "current release directory has an invalid name"
elif [[ -e "$expected_path/.cd-current" ]]; then
  fail "current release marker exists but is not a symlink"
fi

archive_file=$(mktemp /tmp/budget-management-web-deploy.XXXXXXXX.tar)
stage_dir=
temporary_override=
services_stopped=0
new_stack_started=0
backup_dir=

compose_run() {
  local compose_dir=$1
  shift
  local -a args=(docker compose --project-name "$project" -f "$compose_dir/docker-compose.yml")
  if [[ "$compose_dir" != "$expected_path" ]]; then
    local compose_sha=${compose_dir##*/}
    [[ "$compose_sha" =~ ^[0-9a-f]{40}$ ]] || fail "invalid release directory"
    [[ -f "$overrides/$compose_sha.yml" && ! -L "$overrides/$compose_sha.yml" ]] || fail "release Compose override is missing"
    args+=(-f "$overrides/$compose_sha.yml")
  fi
  "${args[@]}" "$@"
}

on_exit() {
  local status=$?
  trap - EXIT
  if (( status != 0 && services_stopped )); then
    if (( new_stack_started )); then
      compose_run "$releases/$deploy_sha" stop app backup caddy >/dev/null 2>&1 || true
    fi
    printf 'Deployment failed; restarting the previous application release.\n' >&2
    if compose_run "$previous_release" up -d --no-build app backup caddy; then
      printf 'Previous application code was restarted; production data was left in place.\n' >&2
    else
      printf 'Automatic code rollback failed. Existing data backups are retained at %s.\n' "$backup_dir" >&2
    fi
  fi
  if [[ -n "$stage_dir" && -d "$stage_dir" ]]; then
    rm -rf -- "$stage_dir"
  fi
  if [[ -n "$temporary_override" && -f "$temporary_override" ]]; then
    rm -f -- "$temporary_override"
  fi
  if [[ -n "$archive_file" && -f "$archive_file" ]]; then
    rm -f -- "$archive_file"
  fi
  exit "$status"
}
trap on_exit EXIT

# Consume and bound the uploaded archive before extracting any file.
python3 - "$archive_file" <<'PY'
import sys

limit = 512 * 1024 * 1024
total = 0
with open(sys.argv[1], "wb") as output:
    while True:
        chunk = sys.stdin.buffer.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise SystemExit("archive exceeds the 512 MiB upload limit")
        output.write(chunk)
PY
chmod 0600 "$archive_file"

release_dir="$releases/$deploy_sha"
if [[ -e "$release_dir" || -L "$release_dir" ]]; then
  [[ -d "$release_dir" && ! -L "$release_dir" ]] || fail "release path exists and is not a directory"
else
  stage_dir=$(mktemp -d "$releases/.staging-$deploy_sha.XXXXXXXX")
  python3 - "$archive_file" "$stage_dir" <<'PY'
import os
import shutil
import sys
import tarfile

archive_path, destination = sys.argv[1:]
seen = set()
total_size = 0
max_members = 50000
max_unpacked = 2 * 1024 * 1024 * 1024
blocked_roots = {".env", "runtime", "backups", "releases", ".cd-current", ".cd-overrides"}

with tarfile.open(archive_path, "r:") as archive:
    members = archive.getmembers()
    if not members or len(members) > max_members:
        raise SystemExit("archive is empty or has too many entries")
    for member in members:
        name = member.name[:-1] if member.isdir() and member.name.endswith("/") else member.name
        if not name or name.startswith("/") or "\\" in name or "\x00" in name:
            raise SystemExit("archive contains an unsafe path")
        parts = name.split("/")
        if any(part in ("", ".", "..") for part in parts) or parts[0] in blocked_roots:
            raise SystemExit("archive contains a forbidden path")
        if name in seen:
            raise SystemExit("archive contains a duplicate path")
        seen.add(name)
        if not member.isdir() and not member.isfile():
            raise SystemExit("archive contains a link or special file")
        if member.isfile():
            total_size += member.size
            if member.size < 0 or total_size > max_unpacked:
                raise SystemExit("archive exceeds the 2 GiB unpacked size limit")
            output_path = os.path.join(destination, *parts)
            parent = os.path.dirname(output_path)
            os.makedirs(parent, mode=0o755, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(output_path, flags, 0o600)
            source = archive.extractfile(member)
            if source is None:
                os.close(descriptor)
                raise SystemExit("archive member could not be read")
            with os.fdopen(descriptor, "wb") as output, source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                os.fchmod(output.fileno(), 0o755 if member.mode & 0o111 else 0o644)
        else:
            directory = os.path.join(destination, *parts)
            if os.path.lexists(directory) and not os.path.isdir(directory):
                raise SystemExit("archive directory conflicts with a file")
            os.makedirs(directory, mode=0o755, exist_ok=True)
            os.chmod(directory, 0o755)
PY
  for required_file in Dockerfile docker-compose.yml Caddyfile; do
    [[ -f "$stage_dir/$required_file" && ! -L "$stage_dir/$required_file" ]] || fail "archive is missing $required_file"
  done
  chmod 0755 "$stage_dir"
  mv -T -- "$stage_dir" "$release_dir"
  stage_dir=
fi
chmod 0755 "$release_dir"

[[ -d "$release_dir" && ! -L "$release_dir" ]] || fail "release directory is unsafe"
if [[ -e "$release_dir/.env" || -L "$release_dir/.env" ]]; then
  [[ -L "$release_dir/.env" && "$(readlink -f -- "$release_dir/.env")" == "$expected_path/.env" ]] || fail "release .env conflicts with the existing production .env"
else
  ln -s "$expected_path/.env" "$release_dir/.env"
fi
[[ -f "$release_dir/Dockerfile" && -f "$release_dir/docker-compose.yml" && -f "$release_dir/Caddyfile" ]] || fail "release files are incomplete"

image="budget-management-web-app:$deploy_sha"
temporary_override=$(mktemp "$overrides/.$deploy_sha.XXXXXXXX")
cat > "$temporary_override" <<EOF
services:
  app:
    image: $image
  backup:
    image: $image
volumes:
  app_runtime:
    external: true
    name: budget-management-web_app_runtime
  caddy_data:
    external: true
    name: budget-management-web_caddy_data
  caddy_config:
    external: true
    name: budget-management-web_caddy_config
EOF
chmod 0600 "$temporary_override"
mv -T -- "$temporary_override" "$overrides/$deploy_sha.yml"
temporary_override=

compose_config=$(compose_run "$release_dir" config --format json)
printf '%s\n' "$compose_config" | python3 -c '
import json
import pathlib
import sys

config = json.load(sys.stdin)
image, release, runtime_volume = sys.argv[1:]
services = config.get("services", {})
if set(("app", "backup", "caddy")) - set(services):
    raise SystemExit("Compose file is missing a required service")
if config.get("volumes", {}).get("app_runtime", {}).get("name") != runtime_volume:
    raise SystemExit("Compose would not use the existing application data volume")
for name in ("caddy_data", "caddy_config"):
    if config.get("volumes", {}).get(name, {}).get("external") is not True:
        raise SystemExit("Compose would create or replace a Caddy data volume")
for service_name in ("app", "backup"):
    service = services[service_name]
    if service.get("image") != image:
        raise SystemExit("application services do not use the expected commit image")
    context = service.get("build", {}).get("context")
    if not context or pathlib.Path(context).resolve() != pathlib.Path(release).resolve():
        raise SystemExit("application image build context is outside the release directory")
    mounts = service.get("volumes", [])
    if len(mounts) != 1 or mounts[0].get("type") != "volume" or mounts[0].get("source") != "app_runtime" or mounts[0].get("target") != "/app/runtime":
        raise SystemExit("application service has an unexpected data mount")
    for key in ("privileged", "devices", "volumes_from", "network_mode", "pid", "ipc"):
        if service.get(key):
            raise SystemExit("application service requests an unsafe Docker option")
    if service.get("ports"):
        raise SystemExit("application service exposes a host port")
caddy = services["caddy"]
if caddy.get("image") != "caddy:2.10-alpine" or caddy.get("build"):
    raise SystemExit("Caddy image configuration is unexpected")
caddy_mounts = caddy.get("volumes", [])
if len(caddy_mounts) != 3:
    raise SystemExit("Caddy has unexpected mounts")
by_target = {mount.get("target"): mount for mount in caddy_mounts}
if set(by_target) != {"/etc/caddy/Caddyfile", "/data", "/config"}:
    raise SystemExit("Caddy mounts are unexpected")
caddyfile_mount = by_target["/etc/caddy/Caddyfile"]
if caddyfile_mount.get("type") != "bind" or pathlib.Path(caddyfile_mount.get("source", "")).resolve() != pathlib.Path(release, "Caddyfile").resolve() or not caddyfile_mount.get("read_only"):
    raise SystemExit("Caddyfile mount is not read-only within this release")
for target, source in (("/data", "caddy_data"), ("/config", "caddy_config")):
    if by_target[target].get("type") != "volume" or by_target[target].get("source") != source:
        raise SystemExit("Caddy data volume mapping is unexpected")
if caddy.get("ports") != [{"host_ip": "127.0.0.1", "published": "8081", "target": 80, "protocol": "tcp", "mode": "ingress"}]:
    raise SystemExit("Caddy port mapping is unexpected")
for key in ("privileged", "devices", "volumes_from", "network_mode", "pid", "ipc"):
    if caddy.get(key):
        raise SystemExit("Caddy service requests an unsafe Docker option")
' "$image" "$release_dir" "$runtime_volume" <<< "$compose_config"

docker image inspect caddy:2.10-alpine >/dev/null 2>&1 || fail "the existing Caddy image is missing; refusing an implicit image pull"
compose_run "$release_dir" build app

stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir=$(mktemp -d "$backup_root/$stamp-$deploy_sha.XXXXXXXX")
chmod 0700 "$backup_dir"

services_stopped=1
compose_run "$previous_release" stop app backup
docker run --rm --network none --user 0:0 \
  --mount "type=volume,src=$runtime_volume,dst=/source,readonly" \
  --mount "type=bind,src=$backup_dir,dst=/backup" \
  --entrypoint python \
  "$image" -c '
import pathlib
import sqlite3
import tarfile

source_db = pathlib.Path("/source/db.sqlite3")
if not source_db.is_file():
    raise SystemExit("production SQLite database is missing")
with sqlite3.connect(f"file:{source_db}?mode=ro", uri=True) as source:
    with sqlite3.connect("/backup/sqlite-consistent.sqlite3") as backup:
        source.backup(backup)
        result = backup.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SystemExit(f"SQLite backup integrity check failed: {result}")
with tarfile.open("/backup/runtime-before.tar.gz", "w:gz") as archive:
    archive.add("/source", arcname="runtime", recursive=True)
'
chmod 0600 "$backup_dir/runtime-before.tar.gz" "$backup_dir/sqlite-consistent.sqlite3"
tar -tzf "$backup_dir/runtime-before.tar.gz" >/dev/null
sha256sum "$backup_dir/runtime-before.tar.gz" "$backup_dir/sqlite-consistent.sqlite3" > "$backup_dir/SHA256SUMS"
chmod 0600 "$backup_dir/SHA256SUMS"
printf '%s\n' "$deploy_sha" > "$backup_dir/deployment-sha"
chmod 0600 "$backup_dir/deployment-sha"

new_stack_started=1
compose_run "$release_dir" up -d --no-build app backup caddy

ready=0
for attempt in {1..60}; do
  if health_host=$(compose_run "$release_dir" exec -T app python -c 'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings"); import django; django.setup(); from django.conf import settings; print(settings.ALLOWED_HOSTS[0])' 2>/dev/null) \
    && [[ "$health_host" =~ ^[A-Za-z0-9.*:-]+$ ]] \
    && compose_run "$release_dir" exec -T app python -c 'import os; from urllib.request import Request, urlopen; os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings"); import django; django.setup(); from django.conf import settings; request = Request("http://127.0.0.1:8000/login/", headers={"Host": settings.ALLOWED_HOSTS[0], "X-Forwarded-Proto": "https"}); response = urlopen(request, timeout=5); assert response.status == 200, response.status' >/dev/null 2>&1 \
    && compose_run "$release_dir" exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 \
    && curl --silent --show-error --fail --max-time 5 -H "Host: $health_host" http://127.0.0.1:8081/login/ -o /dev/null 2>/dev/null; then
    ready=1
    break
  fi
  sleep 2
done
if (( ! ready )); then
  compose_run "$release_dir" ps --all >&2
  fail "application or reverse proxy did not become ready within 120 seconds"
fi

next_marker="$expected_path/.cd-current.$$.tmp"
ln -s "$release_dir" "$next_marker"
mv -Tf -- "$next_marker" "$expected_path/.cd-current"
services_stopped=0
new_stack_started=0

printf 'Deployment %s succeeded. Data snapshot retained at %s\n' "$deploy_sha" "$backup_dir"
