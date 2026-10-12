# French A1 Daily Stories — Build Guide

## Goal

Build a low-maintenance Python application that **generates one original French A1 learning lesson per day**, stores it, and prepares it for publication on a dedicated Substack newsletter. English is the learner's reference language. **French only** for v1.

**First milestone:** reliably create and review 30 distinct daily lessons. Publishing to Substack is a separate, replaceable integration because Substack does not document a general-purpose public post-creation API. Do not let publishing block the content pipeline.

## What each post contains

1. **Title** in French plus an English subtitle.
2. **Original French story**, 120–180 words, beginner-friendly (CEFR A1); a clear beginning, middle and end.
3. **Natural English translation** of the complete story, paragraph for paragraph.
4. **8–10 useful vocabulary entries**: French word or expression, English meaning, example usage taken from the story where possible.
5. **One short grammar explanation**, in English, illustrating something actually used in the story.
6. **Three comprehension questions** in simple French, and answers behind a clearly separated answer section.
7. **Optional CTA**: “Get a new beginner French story in your inbox every day.”

Use a consistent editorial template. Avoid invented claims about current news, and do not try to cover breaking news in the MVP. Prefer evergreen situations such as shopping, transport, family, food, appointments, and travel.

### Example post layout

```markdown
# Le petit café — The Little Café

*French level: A1 | Approx. 3-minute read*

## 📖 L'histoire en français

Marie entre dans un petit café. Elle cherche une table...

## 🇬🇧 English translation

Marie walks into a small café. She is looking for a table...

## 📚 Vocabulary

| Français | English |
|---|---|
| un café | a café / a coffee |
| chercher | to look for |

## 🧠 Grammar tip

**Elle cherche** means “she is looking for.” In French, *elle* means “she.”

## ✍️ Comprehension questions

1. Où est Marie ?
2. Que cherche-t-elle ?
3. ...

## ✅ Answers

1. Elle est dans un café.
2. Elle cherche une table.
3. ...
```

## Tech stack

- **Python 3.11+**
- **OpenAI API** for structured content generation (`openai` Python SDK, `pydantic` for schema validation)
- **SQLite** for story history and publication state (no separate database server)
- **Markdown + JSON** files as durable generated artifacts; optional HTML rendering
- **Linux cron** on an existing VPS (or GitHub Actions on a schedule)
- **Substack** as the frontend publication, starting with human-reviewed copy/paste; optional experimental browser automation after validation

## Project structure

```text
french-story-bot/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── src/
│   └── french_bot/
│       ├── __init__.py
│       ├── config.py          # environment variables
│       ├── schema.py          # Pydantic output models
│       ├── topics.py          # category rotation, recent history
│       ├── generate.py        # OpenAI call
│       ├── validate.py        # structural + editorial checks
│       ├── render.py          # lesson -> Markdown/HTML
│       ├── storage.py         # SQLite + files
│       ├── publisher.py       # replaceable Substack adapter
│       └── cli.py             # command-line entrypoint
├── scripts/
│   └── run_daily.sh
├── data/                     # SQLite file (not committed)
├── output/                   # rendered stories (not committed)
└── tests/
    ├── test_validation.py
    ├── test_render.py
    └── test_duplicate_date.py
```

## Environment configuration

`.env.example`:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
TZ=Europe/London
OUTPUT_DIR=./output
DATABASE_PATH=./data/stories.sqlite3
PUBLISH_MODE=local
SUBSTACK_PUBLICATION_URL=
```

Choose a model currently available in your API account that supports structured outputs. **Never put your API key or Substack session credentials in Git.** Add `.env`, `data/`, and `output/` to `.gitignore`.

`requirements.txt`:

```text
openai>=1.0
pydantic>=2.0
python-dotenv>=1.0
markdown>=3.0
```

For production, resolve and pin tested dependency versions in a lockfile.

## 1. Define the structured lesson output

In `schema.py`, use Pydantic models for:

```python
from pydantic import BaseModel


class VocabularyItem(BaseModel):
    french: str
    english: str
    example_french: str


class Question(BaseModel):
    question_french: str
    answer_french: str


class Lesson(BaseModel):
    title_french: str
    title_english: str
    topic: str
    story_french: str
    translation_english: str
    vocabulary: list[VocabularyItem]
    grammar_title: str
    grammar_explanation_english: str
    questions: list[Question]
```

The model's shape does **not** guarantee correctness. Validate lengths, language level, question count, vocabulary count, and translation fidelity separately.

## 2. Generate a new topic each day

Maintain an editorial rotation across categories: daily life, food, family, commuting, travel, shopping, hobbies, school, weather, social interactions, and work. Combine a category with a distinct setting, character, and everyday problem.

On each run:

1. Read the previous 30 story titles, topics, and summaries from SQLite.
2. Pick a category that has not appeared recently.
3. Pass the history and desired category to the model.
4. Reject exact duplicate titles/topics; regenerate once with a different setting if too similar.
5. Store the chosen topic with the completed lesson.

This is **novelty management**, not a promise of genuinely unique stories. A topic becomes a duplicate if the title and scenario are materially the same, even with changed names.

## 3. Generate the lesson with OpenAI

`generate.py` should call the OpenAI **Responses API** with structured output using `client.responses.parse(..., text_format=Lesson)` and retrieve `response.output_parsed`. The chosen model must support structured output.

Suggested generation prompt:

```text
You are an expert writer of graded readers for adult beginner French learners.
Create ONE entertaining, coherent CEFR A1-level French short story.
The intended reader speaks English and is learning French.

REQUIREMENTS:
- French story: 120–180 words, counting whitespace-separated words.
- Present tense wherever possible. Prefer common, concrete vocabulary.
- Short sentences and one clear everyday plot with a small resolution.
- Avoid complex subordinate clauses, slang, literary past tense, and idioms
  unless explicitly taught.
- Supply a faithful, natural, complete English translation.
- Choose 8–10 genuinely useful French words/phrases from the story.
- Explain one genuine grammar feature appearing in the story in plain English.
- Include exactly 3 answerable comprehension questions in easy French,
  with correct answers.
- No fabricated facts or references to today's news.
- Avoid the recent scenarios provided below; use the assigned category.

ASSIGNED CATEGORY: {category}
RECENT STORIES: {recent_story_summaries}

Return the structured Lesson fields only.
```

Avoid injecting dates, changing prompt versions, or random seeds during reruns unless the run is explicitly a regeneration. Store the model name and prompt version with every lesson.

## 4. Validate content before saving

Implement checks for:

- French story contains roughly 120–180 whitespace-separated words.
- Exactly 3 questions and between 8 and 10 vocabulary entries.
- All vocabulary French phrases appear in the story, when possible.
- Nonempty translation, grammar explanation, answers and title.
- Title and topic are not repeats of the last 30.
- No accidental Polish or other-language story.
- No HTML/scripts/embedded links generated by the model.

Then optionally perform **a second model pass** as a language-editor check: assess A1 difficulty, grammar, translation accuracy, and question/answer consistency. If the review fails, regenerate once and save as `needs_review` if it still fails. Programmatic word counts cannot establish CEFR level or translation quality.

## 5. Store and render the lesson

Suggested SQLite table:

```sql
CREATE TABLE IF NOT EXISTS lessons (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  publication_date TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL,
  topic TEXT NOT NULL,
  title TEXT NOT NULL,
  lesson_json TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'generated',
  substack_post_id TEXT,
  created_at TEXT NOT NULL
);
```

Save for example:

```text
output/2026-10-13/lesson.json
output/2026-10-13/lesson.md
output/2026-10-13/lesson.html
```

Render through one deterministic Markdown template. Do not ask the model to independently reformat the content a second time. Escape untrusted text when generating HTML.

**Idempotency:** on rerun for the same local publication date, return the existing lesson instead of creating another. Use a database uniqueness constraint and a single-process lock to avoid simultaneous runs.

## 6. Substack publishing: three phases

### Phase A — MVP (recommended)

`PUBLISH_MODE=local`: generate the lesson and write Markdown/HTML. Copy the formatted text into Substack, review it, then choose whether to send it by email. This requires no unsupported API.

Substack's official editor supports scheduling a post for a future date and choosing whether to email subscribers. Official instructions: https://support.substack.com/hc/en-us/articles/360037831771-How-do-I-publish-a-new-post-on-Substack

### Phase B — Assisted drafts

Add a `publisher.py` adapter which opens the Substack editor in a visible browser, using Playwright, and fills the title/body. Require a human to review and click the final publish/schedule controls. Browser selectors, sessions and rich-text pasting need to be tested against the live site. Never hardcode passwords or work around security challenges.

### Phase C — Experimental fully automated publication

Only if you accept reliability risks, use your own authenticated Substack browser session and Playwright to navigate the editor and publish. **There is no stable, documented general-purpose public Substack posting API to depend on.** Avoid relying on unofficial endpoints in the core app. Do not automate captcha/2FA bypass. Publication or email-sending may be difficult to reverse.

Before enabling unattended publishing, add verification of the live post URL and date; only mark a lesson `published` after verifying success. On uncertain failures, **do not blindly retry**, since that may send duplicate emails. Prefer pausing publication and notifying the operator.

Keep `Publisher.publish(lesson) -> PublishResult` as a small interface so you can replace Substack with Ghost, WordPress or another platform later.

## 7. CLI and daily job

Implement:

```bash
python -m french_bot.cli generate --date 2026-10-13
python -m french_bot.cli generate --date 2026-10-13  # returns existing lesson
python -m french_bot.cli validate --date 2026-10-13
python -m french_bot.cli publish --date 2026-10-13 --mode local
python -m french_bot.cli run-daily
```

`run-daily` should: acquire lock -> resolve date in configured timezone -> find or generate -> validate -> render -> save -> optionally publish -> log result -> release lock.

`scripts/run_daily.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/french-story-bot
/opt/french-story-bot/.venv/bin/python -m french_bot.cli run-daily \
  >> /opt/french-story-bot/daily.log 2>&1
```

Install and create environment:

```bash
cd /opt/french-story-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Cron (8:00 **server local time**; configure server timezone to `Europe/London` or explicitly schedule timezone in a systemd timer):

```cron
0 8 * * * /opt/french-story-bot/scripts/run_daily.sh
```

Important: on a UTC server this runs at 08:00 UTC, **not** year-round 08:00 London time. Use a systemd timer with `OnCalendar=*-*-* 08:00:00 Europe/London` if DST-correct 08:00 London delivery matters.

## 8. Logs and failure handling

Log date, title, generation duration, validation result, file paths, publish status, and any errors **without API keys, passwords or cookies**. Notify yourself after repeated failures (email or monitoring service). Retry network/model failures with bounded exponential backoff; **do not** blindly retry ambiguous publication requests.

Database states: `generated`, `needs_review`, `approved`, `publishing`, `published`, `publish_failed`. Store the verified remote URL/ID if it exists.

## 9. Testing / acceptance criteria

- [ ] Generates a 120–180-word French A1 story with coherent English translation.
- [ ] Produces 8–10 vocabulary entries, 1 grammar tip, 3 questions and answers.
- [ ] Creates readable Markdown, JSON and HTML files.
- [ ] Running twice for the same date does not create or publish duplicates.
- [ ] Generates 7 days of distinct topics in a local test.
- [ ] Invalid or incomplete output is rejected or flagged for review.
- [ ] Missing API key and model failures fail safely with useful logs.
- [ ] Substack publishing is **off** by default and can be enabled independently.
- [ ] Secrets are excluded from Git and error logs.

## 10. Scope and rollout

**Build first:** generation, structured validation, SQLite, Markdown renderer, CLI, cron. **Then:** 7 manually reviewed drafts and 30 daily lessons. **Only afterwards:** optional Substack browser workflow and paid content/levels (A2/B1, audio, PDF packs).

Do not build a dashboard, accounts system, payments backend, multi-language architecture, images, or scraping into v1. Substack manages subscribers and payments. Focus on producing useful learning material readers actually open.

## Documentation

- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Substack: creating and scheduling a post](https://support.substack.com/hc/en-us/articles/360037831771-How-do-I-publish-a-new-post-on-Substack)
