"""Deterministic screening, not a proof of CEFR level or translation fidelity."""

import re
import unicodedata
from difflib import SequenceMatcher

from langdetect import DetectorFactory, LangDetectException, detect_langs

from .schema import Lesson, ValidationReport
from .topics import HistoryItem

DetectorFactory.seed = 0
UNSAFE = re.compile(
    r"<[^>]*>|(?:https?://|www\.|javascript:|data:|mailto:)|"
    r"!?\[[^\]]*\]\s*\([^)]*\)|^\s*\[[^\]]+\]:|```",
    re.IGNORECASE | re.MULTILINE,
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return " ".join(re.findall(r"\w+", text, re.UNICODE))


def strings(value, path="lesson"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from strings(child, f"{path}[{index}]")


def paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]


def validate_lesson(lesson: Lesson, history: list[HistoryItem] = ()) -> ValidationReport:
    report = ValidationReport(word_count=len(lesson.story_french.split()))
    if not 120 <= report.word_count <= 180:
        report.errors.append(f"Story must contain 120–180 words; found {report.word_count}.")
    if len(lesson.questions) != 3:
        report.errors.append("Exactly 3 comprehension questions are required.")
    if not 8 <= len(lesson.vocabulary) <= 10:
        report.errors.append("Between 8 and 10 vocabulary entries are required.")
    for path, value in strings(lesson.model_dump()):
        if not value.strip():
            report.errors.append(f"{path} must not be empty.")
        if UNSAFE.search(value):
            report.errors.append(f"{path} contains markup or a link; use plain text only.")
    if len(paragraphs(lesson.story_french)) != len(paragraphs(lesson.translation_english)):
        report.errors.append("French and English must have matching paragraph counts.")
    story = f" {normalize(lesson.story_french)} "
    seen = set()
    for index, item in enumerate(lesson.vocabulary, 1):
        phrase = normalize(item.french)
        if phrase in seen:
            report.errors.append(f"Vocabulary entry {index} is repeated.")
        seen.add(phrase)
        if f" {phrase} " not in story:
            report.errors.append(f"Vocabulary entry {index} must appear verbatim in the story.")
        if f" {normalize(item.example_french)} " not in story:
            report.errors.append(f"Vocabulary example {index} must be an excerpt from the story.")
    title, topic = normalize(lesson.title_french), normalize(lesson.topic)
    for previous in history:
        if title == normalize(previous.title) or topic == normalize(previous.topic):
            report.errors.append(f"Title or topic duplicates {previous.publication_date}.")
        elif SequenceMatcher(None, topic, normalize(previous.topic)).ratio() >= 0.88:
            report.errors.append(f"Topic is too similar to {previous.publication_date}.")
    for label, text, expected in (
        ("Story", lesson.story_french, "fr"),
        ("Translation", lesson.translation_english, "en"),
    ):
        try:
            languages = detect_langs(text)
            if languages[0].lang != expected or languages[0].prob < 0.80:
                report.errors.append(f"{label} language check failed (expected {expected}).")
        except LangDetectException:
            report.errors.append(f"{label} language could not be identified.")
    report.warnings.append(
        "Human review is required for A1 level, translation, and scenario novelty."
    )
    return report
