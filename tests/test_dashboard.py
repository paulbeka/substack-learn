import logging
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from french_bot.config import ConfigurationError
from french_bot.dashboard import DashboardSettings, create_app
from french_bot.validate import validate_lesson


@pytest.fixture
def web(settings, tmp_path):
    config = DashboardSettings(
        "reader", "test-password-at-least-16", ("testserver",), False, tmp_path / "logs"
    )
    app = create_app(settings, config)
    with TestClient(app) as client:
        client.auth = (config.username, config.password)
        yield client, app


def save(app, lesson, day, approved=False):
    storage = app.state.storage
    report = validate_lesson(lesson)
    storage.insert(day, "food", lesson, "test", "test", report, None)
    if approved:
        storage.set_review(day, report, "approved", "2026-01-01T12:00:00+00:00")


def token(client):
    return re.search(r'name="csrf-token" content="([^"]+)"', client.get("/").text)[1]


@pytest.mark.parametrize(
    "path", ["/", "/api/status", "/assets/dashboard.js", "/assets/dashboard.css"]
)
def test_private_routes_require_auth(web, path):
    client, _app = web
    client.auth = None
    assert client.get(path).status_code == 401
    client.auth = ("reader", "wrong-password")
    assert client.get(path).status_code == 401


def test_today_archive_safe_html_and_status(web, settings, lesson):
    client, app = web
    day = settings.today().isoformat()
    save(app, lesson, day, approved=True)
    old = lesson.model_copy(update={"title_french": '<script>alert("x")</script>'})
    save(app, old, "2020-01-01")
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="copy-button"' in response.text
    assert "Approved" in response.text and "Checks passed" in response.text
    assert "<table>" in response.text and "<strong>" in response.text and "<ol>" in response.text
    assert "awaiting approval" not in response.text.lower().split('id="article"')[0]
    assert '<script>alert("x")</script>' not in response.text
    past = client.get("/?day=2020-01-01")
    assert "FROM YOUR LIBRARY" in past.text
    assert "&lt;script&gt;" in past.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_missing_today_does_not_show_old_article(web, lesson):
    client, app = web
    save(app, lesson, "2020-01-01")
    response = client.get("/")
    assert 'id="generate-button"' in response.text
    assert 'id="article"' not in response.text
    assert 'id="article"' in client.get("/?day=2020-01-01").text


def test_mutations_require_auth_and_csrf(web, monkeypatch):
    client, app = web
    calls = []
    monkeypatch.setattr(app.state.runner, "submit", lambda *args, **kw: calls.append(args) or True)
    assert client.post("/api/generate").status_code == 403
    assert client.post("/api/generate", headers={"X-CSRF-Token": "invalid"}).status_code == 403
    response = client.post("/api/generate", headers={"X-CSRF-Token": token(client)})
    assert response.status_code == 202 and len(calls) == 1
    client.auth = None
    assert client.post("/api/generate").status_code == 401


def test_existing_article_never_generates_again(web, settings, lesson, monkeypatch):
    client, app = web
    save(app, lesson, settings.today().isoformat())

    def fail(*args, **kwargs):
        pytest.fail("Existing lesson must not submit a job")

    monkeypatch.setattr(app.state.runner, "submit", fail)
    assert client.post("/api/generate", headers={"X-CSRF-Token": token(client)}).json()["exists"]


def test_approve_preserves_existing_service_checks(web, lesson):
    client, app = web
    save(app, lesson, "2020-01-01")
    headers = {"X-CSRF-Token": token(client)}
    assert client.post("/api/approve/2020-01-01").status_code == 403
    assert client.post("/api/approve/2020-01-01", headers=headers).status_code == 200
    assert app.state.storage.get("2020-01-01").approved_at
    bad = lesson.model_copy(update={"questions": []})
    save(app, bad, "2020-01-02")
    assert client.post("/api/approve/2020-01-02", headers=headers).status_code == 409


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/data/stories.sqlite3",
        "/output/2020-01-01/lesson.json",
        "/logs/application.log",
        "/docs",
        "/openapi.json",
        "/assets/.env",
    ],
)
def test_internal_files_not_served(web, path):
    assert web[0].get(path).status_code == 404


def test_invalid_host_and_date(web):
    client, _app = web
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/?day=../../etc/passwd").status_code == 400
    assert client.get("/?page=0").status_code == 400
    client.auth = None
    assert client.get("/healthz").json() == {"status": "ok"}


def test_missing_dashboard_credentials_fail_closed(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "short")
    with pytest.raises(ConfigurationError):
        DashboardSettings.from_env()


def test_secrets_not_rendered_or_logged(settings, tmp_path, lesson):
    settings = replace(settings, api_key="secret-openai-sentinel")
    dashboard = DashboardSettings(
        "user", "secret-password-sentinel", ("testserver",), False, tmp_path / "logs"
    )
    with TestClient(create_app(settings, dashboard)) as client:
        client.auth = (dashboard.username, dashboard.password)
        for path in ("/", "/api/status"):
            text = client.get(path).text
            assert settings.api_key not in text and dashboard.password not in text
        logging.getLogger("french_bot").warning(
            "test redaction: %s %s", settings.api_key, dashboard.password
        )
        log_text = (dashboard.log_dir / "application.log").read_text(encoding="utf-8")
        assert settings.api_key not in log_text and dashboard.password not in log_text
        assert "[REDACTED]" in log_text
