from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_compose_storage_limits_restart_and_loopback_port():
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    app = config["services"]["app"]
    assert len(config["services"]) == 1
    assert app["restart"] == "unless-stopped"
    assert app["environment"]["TZ"] == "Europe/London"
    assert app["environment"]["PUBLISH_MODE"] == "local"
    assert app["environment"]["SCHEDULER_ENABLED"] == "true"
    assert app["env_file"] == [".env"]
    assert "127.0.0.1" in app["ports"][0] and "DASHBOARD_PORT" in app["ports"][0]
    assert set(app["volumes"]) == {
        "stories_data:/app/data",
        "stories_output:/app/output",
        "stories_logs:/app/logs",
    }
    assert len(config["volumes"]) == 3
    assert app["mem_limit"] == "384m" and app["cpus"] <= 1
    assert app["read_only"] and app["cap_drop"] == ["ALL"]


def test_docker_non_root_single_worker_and_secret_exclusion():
    docker = (ROOT / "Dockerfile").read_text()
    assert "USER 10001:10001" in docker
    assert '"--workers", "1"' in docker
    assert "HEALTHCHECK" in docker
    assert "COPY . " not in docker and ".env" not in docker
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert ignore[0] == "**"
    assert not any(line.startswith("!") and ".env" in line for line in ignore)
    runtime = (ROOT / "requirements.runtime.lock").read_text().lower()
    assert "pytest==" not in runtime and "ruff==" not in runtime
    assert "fastapi==" in runtime and "uvicorn==" in runtime
