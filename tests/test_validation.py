import pytest

from french_bot.topics import HistoryItem
from french_bot.validate import validate_lesson


def test_valid_lesson(lesson):
    report = validate_lesson(lesson)
    assert report.passed, report.errors
    assert 120 <= report.word_count <= 180


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("story_french", "Bonjour.", "120–180"),
        ("title_french", " ", "must not be empty"),
        ("translation_english", "", "must not be empty"),
        ("grammar_explanation_english", "<script>alert(1)</script>", "markup or a link"),
        ("title_english", "[click](https://example.com)", "markup or a link"),
        ("topic", "javascript:alert(1)", "markup or a link"),
        ("questions", [], "Exactly 3"),
        ("vocabulary", [], "Between 8 and 10"),
    ],
)
def test_invalid_content(lesson, field, value, error):
    report = validate_lesson(lesson.model_copy(update={field: value}))
    assert not report.passed
    assert any(error in issue for issue in report.errors)


def test_other_language_rejected(lesson):
    lesson.story_french = (
        "To jest mały dom. Moja rodzina mieszka tutaj. Dzisiaj idziemy do sklepu. " * 10
    )
    assert any("expected fr" in error for error in validate_lesson(lesson).errors)


def test_paragraph_alignment(lesson):
    lesson.translation_english = lesson.translation_english.replace("\n\n", " ")
    assert any("paragraph counts" in error for error in validate_lesson(lesson).errors)


def test_vocab_word_boundaries_and_duplicates(lesson):
    lesson.vocabulary[0].french = "caf"
    lesson.vocabulary[1].french = "caf"
    lesson.vocabulary[2].example_french = "Une phrase absente."
    errors = validate_lesson(lesson).errors
    assert any("entry 1 must appear" in error for error in errors)
    assert any("entry 2 is repeated" in error for error in errors)
    assert any("example 3" in error for error in errors)


def test_duplicate_title_ignores_punctuation_case(lesson):
    history = [
        HistoryItem("2026-10-12", "food", lesson.title_french.upper() + " !", "other", "summary")
    ]
    assert any("duplicates" in error for error in validate_lesson(lesson, history).errors)


def test_near_duplicate_scenario(lesson):
    history = [HistoryItem("2026-10-12", "food", "Other", lesson.topic + " today", "summary")]
    assert any("too similar" in error for error in validate_lesson(lesson, history).errors)
