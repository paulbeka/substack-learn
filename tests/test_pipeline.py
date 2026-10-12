import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from french_bot.generate import GenerationError
from french_bot.service import LessonService
from french_bot.storage import Storage
from french_bot.topics import CATEGORIES, HistoryItem, choose_category


def test_duplicate_date_and_artifact_recovery(settings, storage, lesson):
    generator = Mock()
    generator.generate.return_value = lesson
    service = LessonService(settings, storage, generator)
    first = service.generate("2026-10-13")
    (settings.output_dir / "2026-10-13/lesson.html").unlink()
    second = service.generate("2026-10-13")
    assert second == first
    assert generator.generate.call_count == 1
    assert len(storage.list()) == 1
    directory = settings.output_dir / "2026-10-13"
    assert {item.name for item in directory.iterdir()} == {
        "lesson.json",
        "lesson.md",
        "lesson.html",
        "review.json",
    }
    assert (
        json.loads((directory / "lesson.json").read_text(encoding="utf-8"))["title_french"]
        == lesson.title_french
    )
    with pytest.raises(sqlite3.IntegrityError):
        storage.insert("2026-10-13", "food", lesson, "test", "test", first.report, None)


def test_lock_excludes_another_process_and_releases(storage):
    script = "from filelock import FileLock; import sys; FileLock(sys.argv[1], timeout=0).acquire()"
    with storage.lock:
        result = subprocess.run(
            [sys.executable, "-c", script, str(storage.database_path) + ".lock"],
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        assert b"Timeout" in result.stderr
    with Storage(storage.database_path, storage.output_dir).lock:
        pass


def test_seven_days_rotate_and_resume(settings, storage, lesson):
    # Synthetic responses exercise scheduling/history; they are not a language-quality evaluation.
    scenarios = [
        "Buying bread for dinner",
        "Finding a seat on a bus",
        "Choosing a birthday gift",
        "Repairing a bicycle tyre",
        "Preparing a family picnic",
        "Meeting a new colleague",
        "Returning a library book",
    ]
    generator = Mock()
    generator.generate.side_effect = [
        lesson.model_copy(
            update={
                "title_french": f"Histoire {index}",
                "topic": scenario,
            }
        )
        for index, scenario in enumerate(scenarios)
    ]
    service = LessonService(settings, storage, generator)
    for index in range(7):
        service.generate((date(2026, 10, 13) + timedelta(days=index)).isoformat())
    records = storage.list()
    assert len({item.category for item in records}) == 7
    assert len({item.lesson.topic for item in records}) == 7
    assert all(item.status == "generated" for item in records)
    assert len(generator.generate.call_args_list[-1].args[1]) == 6
    for record in records:
        service.generate(record.publication_date)
    assert generator.generate.call_count == 7


def test_lru_category_rotation():
    history = [
        HistoryItem(str(index), category, "t", "p", "s")
        for index, category in enumerate(CATEGORIES)
    ]
    assert choose_category([]) == CATEGORIES[0]
    assert choose_category(history) == CATEGORIES[-1]


def test_invalid_content_retries_once_and_is_flagged(settings, storage, lesson):
    generator = Mock()
    generator.generate.return_value = lesson.model_copy(update={"questions": []})
    record = LessonService(settings, storage, generator).generate("2026-10-13")
    assert record.status == "needs_review"
    assert generator.generate.call_count == 2
    assert generator.generate.call_args.args[2]


def test_editor_failure_and_explicit_human_override(settings, storage, lesson, passing_review):
    generator = Mock()
    generator.generate.return_value = lesson
    generator.review.return_value = passing_review.model_copy(
        update={"a1_level": False, "issues": ["Too hard."]}
    )
    service = LessonService(replace(settings, editor_review=True), storage, generator)
    assert service.generate("2026-10-13").status == "needs_review"
    assert generator.review.call_count == 2
    with pytest.raises(ValueError, match="Editor issues"):
        service.approve("2026-10-13")
    approved = service.approve("2026-10-13", accept_editor_issues=True)
    assert approved.status == "approved"
    assert approved.approved_at
    assert service.validate("2026-10-13").status == "approved"
    # A newly requested review can find problems after the earlier human approval.
    assert service.validate("2026-10-13", editor=True).status == "needs_review"
    assert storage.get("2026-10-13").approved_at is None


def test_editor_outage_preserves_draft_for_recovery(settings, storage, lesson, passing_review):
    generator = Mock()
    generator.generate.return_value = lesson
    generator.review.side_effect = GenerationError("connection failure")
    service = LessonService(replace(settings, editor_review=True), storage, generator)
    assert service.generate("2026-10-13").status == "needs_review"
    assert service.validate("2026-10-13").status == "needs_review"
    generator.review.side_effect = None
    generator.review.return_value = passing_review
    repaired = service.validate("2026-10-13", editor=True)
    assert repaired.status == "generated"
    assert repaired.editor_prompt_version


def test_import_resets_approval_and_preserves_revision(settings, storage, lesson):
    generator = Mock()
    generator.generate.return_value = lesson
    service = LessonService(settings, storage, generator)
    service.generate("2026-10-13")
    service.approve("2026-10-13")
    corrected = lesson.model_copy(update={"title_english": "A Quiet Seat"})
    record = service.import_lesson("2026-10-13", corrected)
    assert record.status == "generated"
    assert record.approved_at is None
    with storage.connect() as db:
        row = db.execute("SELECT previous_row_json FROM revisions").fetchone()
    assert json.loads(row[0])["status"] == "approved"


def test_hard_errors_cannot_be_approved(settings, storage, lesson):
    generator = Mock()
    generator.generate.return_value = lesson.model_copy(update={"questions": []})
    service = LessonService(settings, storage, generator)
    service.generate("2026-10-13")
    with pytest.raises(ValueError, match="Fix validation errors"):
        service.approve("2026-10-13", accept_editor_issues=True)


def test_generation_error_leaves_no_partial_row(settings, storage):
    generator = Mock()
    generator.generate.side_effect = GenerationError("connection failure")
    with pytest.raises(GenerationError):
        LessonService(settings, storage, generator).generate("2026-10-13")
    assert storage.list() == []
