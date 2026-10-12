"""CLI exit codes: 0 success, 1 operational failure, 2 content needs review."""

import argparse
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from filelock import Timeout
from pydantic import ValidationError

from .config import ConfigurationError, Settings
from .generate import GenerationError
from .publisher import get_publisher
from .schema import Lesson
from .service import LessonService
from .storage import Storage

log = logging.getLogger("french_bot")


def parse_date(value: str) -> date:
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError
        return result
    except ValueError:
        raise argparse.ArgumentTypeError("Use a date in YYYY-MM-DD format.") from None


def batch_size(value: str) -> int:
    try:
        number = int(value)
        if 1 <= number <= 30:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("--days must be between 1 and 30.")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Generate and review French A1 daily lessons locally."
    )
    sub = root.add_subparsers(dest="command", required=True)
    for name, description in (
        ("generate", "Generate once for a date; reuse an existing lesson."),
        ("validate", "Recheck saved content, optionally with an AI editor."),
        ("publish", "Export files for manual Substack publication."),
        ("run-daily", "Generate/reuse, validate and export today's lesson."),
        ("approve", "Record that you have personally reviewed the lesson."),
        ("import", "Replace a saved lesson with corrected JSON, preserving a revision."),
    ):
        command = sub.add_parser(name, help=description)
        command.add_argument("--date", type=parse_date, help="Defaults to today's date in TZ.")
        if name == "validate":
            command.add_argument(
                "--editor", action="store_true", help="Make a paid AI editor call."
            )
        if name == "publish":
            command.add_argument("--mode", choices=["local"], default="local")
        if name == "approve":
            command.add_argument(
                "--accept-editor-issues",
                action="store_true",
                help="Accept remaining AI editor concerns after personal review.",
            )
        if name == "import":
            command.add_argument("--file", required=True, type=Path)
    batch = sub.add_parser("batch", help="Generate 1–30 dated lessons; safe to resume.")
    batch.add_argument("--start", required=True, type=parse_date)
    batch.add_argument("--days", type=batch_size, default=30)
    sub.add_parser("list", help="List dates, review state, categories and titles.")
    return root


class RedactSecrets(logging.Filter):
    def __init__(self, secret: str):
        super().__init__()
        self.secret = secret

    def filter(self, record):
        message = record.getMessage()
        if self.secret:
            message = message.replace(self.secret, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


def show(record, settings: Settings) -> int:
    title = " ".join(record.lesson.title_french.split())
    if settings.api_key:
        title = title.replace(settings.api_key, "[REDACTED]")
    print(f"{record.publication_date} | {record.status} | {title}")
    print(f"Files: {settings.output_dir / record.publication_date}")
    for issue in record.report.errors:
        log.warning("validation: %s", issue)
    if record.report.editor_error:
        log.warning("%s", record.report.editor_error)
    if record.report.editor and not record.report.editor.passed:
        # Free-form model issues are kept in review.json, not echoed to logs.
        log.warning("AI editor has concerns; read review.json before approval.")
    return 2 if record.status == "needs_review" else 0


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Avoid SDK HTTP logs and raw exception bodies containing request details.
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("openai").setLevel(logging.CRITICAL)
    try:
        settings = Settings.from_env()
        for handler in logging.getLogger().handlers:
            handler.addFilter(RedactSecrets(settings.api_key))
        storage = Storage(settings.database_path, settings.output_dir)
        with storage.lock:
            service = LessonService(settings, storage)
            if args.command == "list":
                for record in storage.list():
                    show(record, settings)
                return 0
            if args.command == "batch":
                result = 0
                for offset in range(args.days):
                    day = (args.start + timedelta(days=offset)).isoformat()
                    result = max(result, show(service.generate(day), settings))
                return result
            day = (args.date or settings.today()).isoformat()
            if args.command in {"generate", "run-daily"}:
                record = service.generate(day)
                if args.command == "run-daily":
                    record = service.validate(day)
                    result = get_publisher(
                        settings.publish_mode, storage, settings.include_cta
                    ).publish(record)
                    log.info("date=%s publish_status=%s", day, result.status)
            elif args.command == "validate":
                record = service.validate(day, args.editor)
            elif args.command == "approve":
                record = service.approve(day, args.accept_editor_issues)
            elif args.command == "import":
                lesson = Lesson.model_validate_json(args.file.read_text(encoding="utf-8-sig"))
                record = service.import_lesson(day, lesson)
            else:
                record = service.require(day)
                result = get_publisher(args.mode, storage, settings.include_cta).publish(record)
                log.info(
                    "date=%s publish_status=%s; copy into Substack after review", day, result.status
                )
            return show(record, settings)
    except Timeout:
        log.error("Another process is using this database. Wait for it to finish, then rerun.")
    except ValidationError:
        log.error(
            "Invalid lesson JSON/schema. Check field names and types; the existing lesson is unchanged."
        )
    except (ConfigurationError, GenerationError, ValueError) as exc:
        log.error("%s", exc)
    except (OSError, sqlite3.Error) as exc:
        log.error(
            "Storage/file operation failed (%s). Check paths, permissions and free space, then rerun.",
            type(exc).__name__,
        )
    except Exception as exc:  # noqa: BLE001 -- CLI boundary must not print secret-bearing tracebacks.
        log.error(
            "Unexpected failure (%s); no remote publication was attempted.", type(exc).__name__
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
