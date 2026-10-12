from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from french_bot.cli import main
from french_bot.config import Settings
from french_bot.publisher import get_publisher


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in (
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "TZ",
        "PUBLISH_MODE",
        "EDITOR_REVIEW",
        "INCLUDE_CTA",
        "OPENAI_TIMEOUT_SECONDS",
        "OPENAI_MAX_RETRIES",
        "DATABASE_PATH",
        "OUTPUT_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


def test_missing_key_fails_helpfully(caplog):
    assert main(["generate", "--date", "2026-10-13"]) == 1
    assert "OPENAI_API_KEY is missing" in caplog.text


def test_cli_batch_rerun_local_publish_and_import(monkeypatch, lesson, tmp_path):
    monkeypatch.setenv("EDITOR_REVIEW", "false")
    generator = Mock()
    generator.generate.return_value = lesson
    monkeypatch.setattr("french_bot.service.OpenAIGenerator", lambda settings: generator)
    assert main(["generate", "--date", "2026-10-13"]) == 0
    assert main(["run-daily", "--date", "2026-10-13"]) == 0
    assert main(["publish", "--date", "2026-10-13", "--mode", "local"]) == 0
    assert main(["approve", "--date", "2026-10-13"]) == 0
    assert (
        main(
            [
                "import",
                "--date",
                "2026-10-13",
                "--file",
                str(tmp_path / "output/2026-10-13/lesson.json"),
            ]
        )
        == 0
    )
    assert main(["list"]) == 0
    assert generator.generate.call_count == 1


def test_invalid_env_and_no_remote_mode(monkeypatch, caplog, storage):
    monkeypatch.setenv("PUBLISH_MODE", "substack")
    assert main(["run-daily"]) == 1
    assert "Only PUBLISH_MODE=local" in caplog.text
    with pytest.raises(ValueError):
        get_publisher("substack", storage)


def test_invalid_date_rejected():
    with pytest.raises(SystemExit) as exc:
        main(["generate", "--date", "../../etc"])
    assert exc.value.code == 2


def test_configured_timezone_controls_day(monkeypatch):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 7, 1, 23, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr("french_bot.config.datetime", Clock)
    assert Settings(timezone="Europe/London").today().isoformat() == "2026-07-02"


def test_bad_json_does_not_leak_content(tmp_path, caplog):
    path = tmp_path / "bad.json"
    path.write_text('{"sensitive-value": "secret-value"}', encoding="utf-8")
    assert main(["import", "--file", str(path)]) == 1
    assert "secret-value" not in caplog.text
