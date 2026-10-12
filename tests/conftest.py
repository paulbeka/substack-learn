from pathlib import Path

import pytest

from french_bot.config import Settings
from french_bot.schema import EditorReview, Lesson
from french_bot.storage import Storage


@pytest.fixture
def lesson():
    return Lesson.model_validate_json(
        (Path(__file__).parents[1] / "examples/lesson.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_path=tmp_path / "data/stories.sqlite3",
        output_dir=tmp_path / "output",
        editor_review=False,
    )


@pytest.fixture
def storage(settings):
    return Storage(settings.database_path, settings.output_dir)


@pytest.fixture
def passing_review():
    return EditorReview(
        is_french=True,
        a1_level=True,
        grammar_correct=True,
        translation_faithful=True,
        questions_correct=True,
        grammar_tip_correct=True,
        scenario_distinct=True,
        issues=[],
    )
