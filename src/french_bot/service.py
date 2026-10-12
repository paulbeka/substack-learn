"""Pipeline orchestration. CLI callers hold Storage.lock across each command."""

import logging
from time import monotonic

from .config import Settings
from .generate import EDITOR_PROMPT_VERSION, PROMPT_VERSION, GenerationError, OpenAIGenerator
from .schema import Lesson
from .storage import Storage, StoredLesson, utc_now
from .topics import choose_category
from .validate import validate_lesson

log = logging.getLogger(__name__)


class LessonService:
    def __init__(self, settings: Settings, storage: Storage, generator=None):
        self.settings, self.storage, self._generator = settings, storage, generator

    @property
    def generator(self):
        if self._generator is None:
            self._generator = OpenAIGenerator(self.settings)
        return self._generator

    def require(self, day: str) -> StoredLesson:
        record = self.storage.get(day)
        if record is None:
            raise ValueError("No lesson exists for that date. Run generate first.")
        return record

    def generate(self, day: str) -> StoredLesson:
        existing = self.storage.get(day)
        if existing:
            self.storage.export(existing, self.settings.include_cta)
            log.info("date=%s reused_existing=true status=%s", day, existing.status)
            return existing
        started = monotonic()
        history = self.storage.history(day)
        category = choose_category(history)
        feedback = []
        for attempt in range(2):
            log.info("date=%s generation_attempt=%d category=%s", day, attempt + 1, category)
            lesson = self.generator.generate(category, history, feedback)
            report = validate_lesson(lesson, history)
            if not report.errors and self.settings.editor_review:
                try:
                    report.editor = self.generator.review(lesson, history)
                except GenerationError:
                    # Keep usable content when the optional editor is unavailable.
                    report.editor_error = (
                        "Editor unavailable; retry validation with --editor or review manually."
                    )
                    break
            if report.passed:
                break
            feedback = report.errors.copy()
            if report.editor and not report.editor.passed:
                feedback.append(
                    "The editor rejected the lesson: " + report.editor.model_dump_json()
                )
            feedback.append(
                f"Rejected scenario: {lesson.topic}. Choose a different setting and problem."
            )
        record = self.storage.insert(
            day,
            category,
            lesson,
            self.settings.model,
            PROMPT_VERSION,
            report,
            EDITOR_PROMPT_VERSION if report.editor else None,
        )
        directory = self.storage.export(record, self.settings.include_cta)
        log.info(
            "date=%s title=%r duration_seconds=%.2f validation=%s status=%s path=%s",
            day,
            lesson.title_french,
            monotonic() - started,
            report.passed,
            record.status,
            directory,
        )
        return record

    def validate(self, day: str, editor: bool = False) -> StoredLesson:
        record = self.require(day)
        report = validate_lesson(record.lesson, self.storage.history(day))
        report.editor = record.report.editor
        report.editor_error = record.report.editor_error
        editor_ran = editor and not report.errors
        if editor_ran:
            report.editor = self.generator.review(record.lesson, self.storage.history(day))
            report.editor_error = None
        status = record.status
        if status not in {"published", "publishing", "publish_failed"}:
            if report.errors or (not report.passed and (status != "approved" or editor_ran)):
                status = "needs_review"
            elif status != "approved":
                status = "generated"
        record = self.storage.set_review(
            day,
            report,
            status,
            record.approved_at if status != "needs_review" else None,
            EDITOR_PROMPT_VERSION if editor_ran else None,
        )
        self.storage.export(record, self.settings.include_cta)
        return record

    def approve(self, day: str, accept_editor_issues: bool = False) -> StoredLesson:
        record = self.require(day)
        if record.status in {"published", "publishing", "publish_failed"}:
            raise ValueError("Cannot approve a lesson in a remote publication state.")
        record = self.validate(day)
        if record.report.errors:
            raise ValueError("Fix validation errors with import before approving this lesson.")
        if not record.report.passed and not accept_editor_issues:
            raise ValueError(
                "Editor issues remain. Correct the lesson or use --accept-editor-issues after human review."
            )
        record = self.storage.set_review(day, record.report, "approved", utc_now())
        self.storage.export(record, self.settings.include_cta)
        return record

    def import_lesson(self, day: str, lesson: Lesson) -> StoredLesson:
        record = self.require(day)
        if record.status in {"published", "publishing", "publish_failed"}:
            raise ValueError("Cannot edit a lesson in a remote publication state.")
        report = validate_lesson(lesson, self.storage.history(day))
        record = self.storage.replace(day, lesson, report)
        self.storage.export(record, self.settings.include_cta)
        return record
