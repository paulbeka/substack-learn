from datetime import datetime
from threading import Event
from unittest.mock import Mock

import pytest

from french_bot.scheduler import GenerationRunner, due_date
from french_bot.service import LessonService
from french_bot.storage import Storage


@pytest.mark.parametrize(
    "timestamp,expected",
    [
        ("2026-01-15T07:59:59+00:00", None),
        ("2026-01-15T08:00:00+00:00", "2026-01-15"),
        ("2026-07-15T06:59:59+00:00", None),
        ("2026-07-15T07:00:00+00:00", "2026-07-15"),
        ("2026-03-29T07:00:00+00:00", "2026-03-29"),
        ("2026-10-25T07:00:00+00:00", None),
        ("2026-10-25T08:00:00+00:00", "2026-10-25"),
        ("2026-07-15T22:59:00+00:00", "2026-07-15"),
        ("2026-07-15T23:00:00+00:00", None),
    ],
)
def test_london_8am_with_dst(timestamp, expected):
    assert due_date(datetime.fromisoformat(timestamp)) == expected


def runner_for(settings, storage, generator):
    return GenerationRunner(settings, storage, lambda s, db: LessonService(s, db, generator))


def test_once_per_day_across_restart_and_manual_click(settings, storage, lesson):
    generator = Mock()
    generator.generate.return_value = lesson
    runner = runner_for(settings, storage, generator)
    runner.run("2026-10-13")
    runner.close()
    restarted = runner_for(
        settings, Storage(settings.database_path, settings.output_dir), generator
    )
    restarted.run("2026-10-13")
    restarted.run("2026-10-13", manual=True)
    restarted.close()
    assert generator.generate.call_count == 1
    assert storage.run_status("2026-10-13")["status"] == "succeeded"


def test_failure_is_not_automatically_retried_but_manual_retry_works(settings, storage, lesson):
    generator = Mock()
    generator.generate.side_effect = RuntimeError("secret-should-not-leak")
    runner = runner_for(settings, storage, generator)
    runner.run("2026-10-13")
    runner.run("2026-10-13")
    assert generator.generate.call_count == 1
    assert "secret" not in storage.run_status("2026-10-13")["message"]
    generator.generate.side_effect = None
    generator.generate.return_value = lesson
    runner.run("2026-10-13", manual=True)
    runner.close()
    assert storage.get("2026-10-13")
    assert generator.generate.call_count == 2


def test_interrupted_job_requires_explicit_retry(settings, storage, lesson):
    with storage.lock:
        storage.claim_run("2026-10-13", manual=False)
        storage.recover_runs()
    generator = Mock()
    generator.generate.return_value = lesson
    runner = runner_for(settings, storage, generator)
    runner.run("2026-10-13")
    generator.generate.assert_not_called()
    assert storage.run_status("2026-10-13")["status"] == "interrupted"
    runner.run("2026-10-13", manual=True)
    runner.close()
    assert storage.get("2026-10-13")


def test_concurrent_manual_and_scheduled_job_share_lock(settings, storage, lesson):
    started, release = Event(), Event()
    generator = Mock()

    def slow_generate(*args):
        started.set()
        assert release.wait(5)
        return lesson

    generator.generate.side_effect = slow_generate
    runner = runner_for(settings, storage, generator)
    other = runner_for(settings, Storage(settings.database_path, settings.output_dir), generator)
    try:
        assert runner.submit("2026-10-13", manual=True)
        assert started.wait(5)
        assert not runner.submit("2026-10-13")
        other.run("2026-10-13")
        assert "Another command" in other.notice
    finally:
        release.set()
        runner.close()
        other.close()
    assert generator.generate.call_count == 1
