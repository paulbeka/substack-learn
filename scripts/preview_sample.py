"""Render the bundled, hand-written example without an API key or database changes."""

from pathlib import Path

from french_bot.render import render_html, render_markdown
from french_bot.schema import Lesson
from french_bot.storage import atomic_write
from french_bot.validate import validate_lesson


def main():
    root = Path(__file__).resolve().parents[1]
    lesson = Lesson.model_validate_json((root / "examples/lesson.json").read_text(encoding="utf-8"))
    report = validate_lesson(lesson)
    if report.errors:
        raise SystemExit("Sample validation failed: " + "; ".join(report.errors))
    directory = root / "output/sample"
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write(directory / "lesson.md", render_markdown(lesson))
    atomic_write(directory / "lesson.html", render_html(lesson))
    print(f"Sample: {report.word_count} French words. Open {directory / 'lesson.html'}")


if __name__ == "__main__":
    main()
