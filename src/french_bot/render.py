"""One deterministic Markdown template, with untrusted punctuation escaped."""

import html
import re

import markdown

from .schema import Lesson
from .validate import paragraphs


def plain(text: str) -> str:
    # Escape HTML, then Markdown punctuation; keep the source readable as prose.
    text = html.escape(" ".join(text.split()), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|~>-])", r"\\\1", text)


def body(text: str) -> str:
    return "\n\n".join(plain(paragraph) for paragraph in paragraphs(text))


def render_markdown(lesson: Lesson, include_cta: bool = True) -> str:
    rows = [
        f"# {plain(lesson.title_french)} — {plain(lesson.title_english)}",
        "*French level: A1 | Approx. 3-minute read*",
        "## L'histoire en français",
        body(lesson.story_french),
        "## English translation",
        body(lesson.translation_english),
        "## Vocabulary",
        "| Français | English | Example from the story |\n|---|---|---|\n"
        + "\n".join(
            f"| {plain(item.french)} | {plain(item.english)} | {plain(item.example_french)} |"
            for item in lesson.vocabulary
        ),
        "## Grammar tip",
        f"**{plain(lesson.grammar_title)}**\n\n{body(lesson.grammar_explanation_english)}",
        "## Comprehension questions",
        "\n".join(
            f"{index}. {plain(item.question_french)}"
            for index, item in enumerate(lesson.questions, 1)
        ),
        "---\n\n## Answers\n\n*Try the questions before reading the answers.*",
        "\n".join(
            f"{index}. {plain(item.answer_french)}"
            for index, item in enumerate(lesson.questions, 1)
        ),
    ]
    if include_cta:
        rows.append("Get a new beginner French story in your inbox every day.")
    return "\n\n".join(rows) + "\n"


def render_html(lesson: Lesson, include_cta: bool = True) -> str:
    content = markdown.markdown(render_markdown(lesson, include_cta), extensions=["tables"])
    title = html.escape(lesson.title_french, quote=True)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{max-width: 780px; margin: 3rem auto; padding: 0 1.5rem; color: #20252b;
font: 18px/1.7 Georgia, serif; background: #fffdf8;}}
h1, h2 {{line-height: 1.3;}} h2 {{margin-top: 2rem;}}
table {{width: 100%; border-collapse: collapse; font-size: 0.9em;}}
th, td {{text-align: left; padding: .5rem; border-bottom: 1px solid #ddd;}}
hr {{margin-top: 3rem; border: 0; border-top: 1px solid #ddd;}}
@media print {{body {{margin: 0; max-width: none; background: white;}}}}
</style></head><body><main>
{content}
</main></body></html>
"""
