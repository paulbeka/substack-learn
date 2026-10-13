"""SQLite is authoritative; exported files can always be rebuilt from a row."""

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

from .render import render_html, render_markdown
from .schema import Lesson, ValidationReport
from .topics import HistoryItem

STATES = ("generated", "needs_review", "approved", "publishing", "published", "publish_failed")


@dataclass(frozen=True)
class StoredLesson:
    publication_date: str
    category: str
    lesson: Lesson
    model: str
    prompt_version: str
    status: str
    report: ValidationReport
    created_at: str
    updated_at: str
    editor_prompt_version: str | None = None
    approved_at: str | None = None
    substack_post_id: str | None = None
    remote_url: str | None = None


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Storage:
    def __init__(self, database_path: Path, output_dir: Path):
        self.database_path = database_path.resolve()
        self.output_dir = output_dir.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.database_path) + ".lock", timeout=0)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publication_date TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL, topic TEXT NOT NULL, title TEXT NOT NULL,
                    summary TEXT NOT NULL, lesson_json TEXT NOT NULL,
                    model TEXT NOT NULL, prompt_version TEXT NOT NULL,
                    editor_prompt_version TEXT,
                    status TEXT NOT NULL CHECK (status IN
                      ('generated','needs_review','approved','publishing','published','publish_failed')),
                    validation_json TEXT NOT NULL, approved_at TEXT,
                    substack_post_id TEXT, remote_url TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publication_date TEXT NOT NULL, previous_row_json TEXT NOT NULL,
                    replaced_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generation_runs (
                    publication_date TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed','interrupted')),
                    started_at TEXT NOT NULL, finished_at TEXT, message TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(row) -> StoredLesson:
        return StoredLesson(
            publication_date=row["publication_date"],
            category=row["category"],
            lesson=Lesson.model_validate_json(row["lesson_json"]),
            model=row["model"],
            prompt_version=row["prompt_version"],
            status=row["status"],
            report=ValidationReport.model_validate_json(row["validation_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            editor_prompt_version=row["editor_prompt_version"],
            approved_at=row["approved_at"],
            substack_post_id=row["substack_post_id"],
            remote_url=row["remote_url"],
        )

    def get(self, publication_date: str) -> StoredLesson | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM lessons WHERE publication_date = ?", (publication_date,)
            ).fetchone()
        return self.decode(row) if row else None

    def list(self) -> list[StoredLesson]:
        with self.connect() as db:
            return [
                self.decode(row)
                for row in db.execute("SELECT * FROM lessons ORDER BY publication_date")
            ]

    def archive(self, page: int = 1, size: int = 50) -> list[dict]:
        """Read only sidebar metadata, not every full lesson in the database."""
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT publication_date, title, status FROM lessons "
                    "ORDER BY publication_date DESC LIMIT ? OFFSET ?",
                    (size, (page - 1) * size),
                )
            ]

    def run_status(self, day: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM generation_runs WHERE publication_date=?", (day,)
            ).fetchone()
        return dict(row) if row else None

    def claim_run(self, day: str, manual: bool) -> bool:
        """Caller holds the shared file lock across claim, model work and completion."""
        with self.connect() as db:
            previous = db.execute(
                "SELECT status FROM generation_runs WHERE publication_date=?", (day,)
            ).fetchone()
            if previous and (
                not manual or previous["status"] not in {"failed", "interrupted", "running"}
            ):
                return False
            db.execute(
                "INSERT INTO generation_runs VALUES (?, 'running', ?, NULL, 'Generating lesson.') "
                "ON CONFLICT(publication_date) DO UPDATE SET status='running', started_at=excluded.started_at, "
                "finished_at=NULL, message=excluded.message",
                (day, utc_now()),
            )
        return True

    def finish_run(self, day: str, status: str, message: str):
        with self.connect() as db:
            db.execute(
                "UPDATE generation_runs SET status=?, message=?, finished_at=? WHERE publication_date=?",
                (status, message, utc_now(), day),
            )

    def recover_runs(self):
        """Only call while holding the shared lock: no generator can still be active."""
        with self.connect() as db:
            db.execute(
                "UPDATE generation_runs SET status='interrupted', finished_at=?, "
                "message='The process stopped. Check the saved article before retrying.' "
                "WHERE status='running'",
                (utc_now(),),
            )

    def history(self, exclude_date: str) -> list[HistoryItem]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT publication_date, category, title, topic, summary FROM lessons "
                "WHERE publication_date != ? ORDER BY publication_date DESC LIMIT 30",
                (exclude_date,),
            ).fetchall()
        return [HistoryItem(**dict(row)) for row in rows]

    def insert(
        self, publication_date, category, lesson, model, prompt_version, report, editor_version
    ):
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO lessons
                (publication_date, category, topic, title, summary, lesson_json, model,
                 prompt_version, editor_prompt_version, status, validation_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    publication_date,
                    category,
                    lesson.topic,
                    lesson.title_french,
                    " ".join(lesson.translation_english.split())[:700],
                    lesson.model_dump_json(),
                    model,
                    prompt_version,
                    editor_version,
                    "generated" if report.passed else "needs_review",
                    report.model_dump_json(),
                    now,
                    now,
                ),
            )
        return self.get(publication_date)

    def set_review(
        self,
        publication_date: str,
        report: ValidationReport,
        status: str,
        approved_at: str | None = None,
        editor_version: str | None = None,
    ):
        if status not in STATES:
            raise ValueError("Invalid lesson state.")
        with self.connect() as db:
            db.execute(
                "UPDATE lessons SET validation_json=?, status=?, approved_at=?, updated_at=?, "
                "editor_prompt_version=COALESCE(?, editor_prompt_version) "
                "WHERE publication_date=?",
                (
                    report.model_dump_json(),
                    status,
                    approved_at,
                    utc_now(),
                    editor_version,
                    publication_date,
                ),
            )
        return self.get(publication_date)

    def replace(self, publication_date: str, lesson: Lesson, report: ValidationReport):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM lessons WHERE publication_date=?", (publication_date,)
            ).fetchone()
            db.execute(
                "INSERT INTO revisions (publication_date, previous_row_json, replaced_at) VALUES (?, ?, ?)",
                (publication_date, json.dumps(dict(row), ensure_ascii=False), utc_now()),
            )
            db.execute(
                """UPDATE lessons SET topic=?, title=?, summary=?, lesson_json=?,
                validation_json=?, status=?, approved_at=NULL, editor_prompt_version=NULL,
                updated_at=? WHERE publication_date=?""",
                (
                    lesson.topic,
                    lesson.title_french,
                    " ".join(lesson.translation_english.split())[:700],
                    lesson.model_dump_json(),
                    report.model_dump_json(),
                    "generated" if report.passed else "needs_review",
                    utc_now(),
                    publication_date,
                ),
            )
        return self.get(publication_date)

    def export(self, record: StoredLesson, include_cta: bool = True) -> Path:
        directory = self.output_dir / record.publication_date
        directory.mkdir(parents=True, exist_ok=True)
        metadata = {
            "publication_date": record.publication_date,
            "category": record.category,
            "status": record.status,
            "model": record.model,
            "prompt_version": record.prompt_version,
            "editor_prompt_version": record.editor_prompt_version,
            "approved_at": record.approved_at,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "validation": record.report.model_dump(),
            "remote_url": record.remote_url,
        }
        for name, content in {
            "lesson.json": record.lesson.model_dump_json(indent=2) + "\n",
            "lesson.md": render_markdown(record.lesson, include_cta),
            "lesson.html": render_html(record.lesson, include_cta),
            "review.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        }.items():
            atomic_write(directory / name, content)
        return directory


def atomic_write(path: Path, content: str):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
