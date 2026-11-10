import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("unsafe_volume", [False, True])
def test_compose_validation_consumes_large_config_and_rejects_unsafe_volumes(tmp_path, unsafe_volume):
    release = str(tmp_path / "release")
    image = "budget-management-web:test"
    runtime_volume = "budget-management-web_app_runtime"
    application = {
        "image": image,
        "build": {"context": release},
        "volumes": [{"type": "volume", "source": "app_runtime", "target": "/app/runtime"}],
    }
    config = {
        "services": {
            "app": application,
            "backup": application,
            "caddy": {
                "image": "caddy:2.10-alpine",
                "volumes": [
                    {"type": "bind", "source": f"{release}/Caddyfile", "target": "/etc/caddy/Caddyfile", "read_only": True},
                    {"type": "volume", "source": "caddy_data", "target": "/data"},
                    {"type": "volume", "source": "caddy_config", "target": "/config"},
                ],
                "ports": [{"host_ip": "127.0.0.1", "published": "8081", "target": 80, "protocol": "tcp", "mode": "ingress"}],
            },
        },
        "volumes": {
            "app_runtime": {"name": "unexpected" if unsafe_volume else runtime_volume},
            "caddy_data": {"external": True},
            "caddy_config": {"external": True},
        },
    }
    config_path = tmp_path / "compose.json"
    config_path.write_text(json.dumps(config) + " " * (1024 * 1024))
    source = (Path(__file__).resolve().parents[1] / "scripts/deploy-remote.sh").read_text()
    validation = source.split('compose_config=$(compose_run "$release_dir" config --format json)', 1)[1]
    validation = validation.split("docker image inspect", 1)[0]
    result = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; compose_config=$(cat "$CONFIG_PATH");' + validation],
        env={**os.environ, "CONFIG_PATH": str(config_path), "release_dir": release,
             "image": image, "runtime_volume": runtime_volume},
        capture_output=True, text=True, timeout=10,
    )
    if unsafe_volume:
        assert result.returncode != 0
        assert "Compose would not use the existing application data volume" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
