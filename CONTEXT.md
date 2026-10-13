# Project context: French A1 Daily Stories

This file is the implementation handoff for future development. Read [README.md](README.md) for operational commands and [FRENCH_SUBSTACK_BUILD_GUIDE.md](FRENCH_SUBSTACK_BUILD_GUIDE.md) for the original product brief.

## Implemented scope

French-only, English-reference lessons; one lesson per publication date; OpenAI generation and optional model editing; deterministic validation; SQLite history and review state; JSON/Markdown/HTML exports; manual review and corrections; resumable batches of up to 30 days; a private FastAPI/Jinja2 dashboard; and a Docker deployment with daily London scheduling. Substack is a manual destination. There is no subscriber database, browser automation, automatic publication, payment system or outbound notification integration. Read [DEPLOYMENT.md](DEPLOYMENT.md) for the VPS runbook.

## Data flow

```text
CLI -> .env + environment -> SQLite + OS-backed file lock
    -> resolve date in TZ -> return existing row, if present
    -> newest 30 other dates -> least-recently-used category
    -> Responses structured Lesson -> local checks
    -> optional Responses EditorReview -> one content retry if needed
    -> commit SQLite row -> atomic JSON/Markdown/HTML/review exports
    -> human review -> corrections/import -> explicit approval
    -> human copy/paste and publication in Substack
```

`run-daily` also revalidates the saved result and calls the local publisher. Local export does not change publication status. Generated and flagged lessons both remain inspectable. A generation refusal, malformed schema or API failure before any usable lesson leaves the date unclaimed. An editor outage retains the usable draft and records the failure. There are no model calls on a same-date `generate` rerun.

## Module map

| Module | Responsibility |
|---|---|
| `config.py` | Environment parsing, working-directory-relative paths, London date resolution |
| `schema.py` | Pydantic `Lesson`, nested vocabulary/questions, editor and validation reports |
| `topics.py` | Eleven-category rotation and compact history records |
| `generate.py` | Versioned generation/editor prompts, Responses parsing, safe API errors |
| `validate.py` | Counts, required text, matching paragraphs, French/English detection, vocabulary grounding, markup and duplicate screening |
| `render.py` | Escaped plain-text fields inserted into one Markdown template, then HTML |
| `storage.py` | SQLite, file lock, revision history and recoverable artifact exports |
| `service.py` | Two-attempt generation, editor fallback, validation, approval and import orchestration |
| `publisher.py` | `Publisher.publish(StoredLesson) -> PublishResult`; only `LocalPublisher` exists |
| `cli.py` | Commands, whole-command locking, redacted logs, exit codes |
| `dashboard.py` | Basic authentication, CSRF-protected mutations, archive/article rendering, lifespan and rotating logs |
| `scheduler.py` | Single background worker, persistent daily claims, 08:00 London polling and crash recovery |
| `templates/dashboard.html` | Autoescaped private reading room; only the escaped article renderer returns trusted markup |
| `static/dashboard.js` | Rich HTML + text copying, explicit selection fallback, generation polling and approval |

## Storage and state

SQLite is authoritative. `lessons.publication_date` has a unique constraint. Stored fields include the lesson JSON, category, topic, French title, summary (first 700 characters of normalized English translation), model, generation/editor prompt versions, validation JSON, timestamps and approval. Remote URL/ID fields are reserved. `revisions` snapshots previous rows before a corrected JSON import; the original generation model/version remain provenance after import, while the old editor version and approval are cleared.

States used now:

- `generated`: local checks and any requested editor pass succeeded; awaits human review.
- `needs_review`: local/editor failure or editor unavailable.
- `approved`: human explicitly approved; the timestamp records that action.

`publishing`, `published` and `publish_failed` are reserved in the database for a future verified remote adapter. No v1 command sets them. Import and approval reject rows in those states. An explicit human override of AI editor concerns stays approved on ordinary revalidation; new local errors or a newly requested failing editor review remove approval. Existing editor concerns remain in the report after an override.

An import accepts only the `Lesson` schema (not `review.json`). It can save invalid editorial content as `needs_review`, but cannot import missing/wrongly typed schema fields. All imports clear prior approval. No automatic destructive regeneration command exists; edit and import a replacement lesson for the same date.

## Invariants to preserve

1. Hold `Storage.lock` for the entire CLI command, including network calls, review mutations and artifact writes. Service methods assume their caller holds the lock. Batch holds it for the whole batch. The lock is derived from the resolved database path; SQLite uniqueness is the second line of defence.
2. Never overwrite an existing date implicitly. `generate` returns it and restores files. Use the same database when resuming a job.
3. Commit the row before exporting. Files are each written to a temporary sibling, flushed and replaced. They are not a multi-file transaction, so an interrupted export is repaired by rerun.
4. Dates accepted by the CLI are canonical `YYYY-MM-DD`. Do not pass unvalidated user path fragments into export folder names.
5. Validate before saving. A shape-valid failed lesson is saved as `needs_review`, never approved. Hard errors cannot be overridden through `approve`.
6. Treat generated content as plain text. Escape HTML and Markdown punctuation even for invalid drafts; never inject a model response directly into HTML.
7. Keep credentials out of reports, prompts, database rows and logs. SDK error bodies/tracebacks are suppressed at the CLI boundary. Only safe error classes/status codes are shown. The configured API key is redacted from application logs and displayed titles.
8. Model changes or prompt changes affect future generations, not saved dates. Bump `PROMPT_VERSION`/`EDITOR_PROMPT_VERSION` when changing their respective prompts. Do not add dates or random seeds to a normal generation prompt.
9. Do not label local exports as published. A future remote adapter must gate on approval, persist in-flight state, verify remote URL/date, and reconcile ambiguous outcomes before retrying. Never automatically retry a potentially successful email/publication request.

## Validation and novelty limits

Story word counts use whitespace splitting. Vocabulary and examples must appear as normalized whole phrases; case, punctuation and apostrophe typography are normalized. This is stricter than accepting a dictionary infinitive absent from the story, so the prompt explicitly requests the actual inflected form. The `langdetect` seed is fixed, but language detection is still heuristic. The English translation must have the same number of blank-line-separated paragraphs as the story.

Exact normalized title/topic repeats and topic similarity at or above 0.88 are errors. This cannot detect every paraphrased plot or changed character name. The enabled-by-default editor receives recent summaries and checks scenario distinctness along with A1 level, grammar, translation, grammar-tip evidence, and question/answer correctness. Human review remains necessary. Set `EDITOR_REVIEW=false` to skip the extra generation-time call; local checks alone cannot establish language quality.

History is the latest 30 publication dates excluding the current date, including later dates if backfilling. Category selection prefers the first unused category, otherwise the one whose latest occurrence is oldest. Database history tracks saved drafts even if they need review. Summaries are translation excerpts, not separately generated summaries.

## Reliability and operations

The SDK handles transient connection/rate-limit/server errors with bounded backoff (`OPENAI_MAX_RETRIES`, default two retries). Content validation has a separate maximum of two generation attempts. No unbounded retries exist. Batches persist each completed date, continue past content failures and stop on operational failures. JSON/schema/model-refusal failures are rejected rather than persisted.

Local validation and import require no key. An explicit `validate --editor` does require one. A failed requested editor recheck leaves the existing stored row unchanged. Automatic generation-time editor failure retains the newly generated row as `needs_review`.

`requirements.lock` contains pinned runtime and development dependencies. `requirements.runtime.lock` excludes development tools for the Docker image. Regenerate both from the installed environment using `scripts/lock_dependencies.py`. The project is installed separately. `tzdata` supports IANA timezones on Windows. Docker starts the built-in scheduler; the older host cron/systemd examples are alternatives, not additional schedules. Alerts are delegated to a monitoring service watching failures. This is a single-host design with local storage; avoid network filesystems or independently configured database copies.

## Dashboard and Docker architecture

`create_app()` reads existing pipeline settings, then requires a dashboard username and password (16+ characters). The CLI still works without dashboard credentials. One Uvicorn process serves HTTP and one `ThreadPoolExecutor` worker handles generation. The scheduler submits at/after 08:00 Europe/London, polling every 30 seconds, with UTC offsets calculated using `zoneinfo` on each tick. Startup after 08:00 catches up today only.

`generation_runs` is an additive table keyed by publication date. A worker acquires the same database file lock used by the CLI, checks for an existing lesson, and commits a `running` claim before making API calls. Automatic work never retries any recorded attempt. Repeated manual clicks cannot queue an unlimited number of jobs; an active future rejects further submissions. Failures become `failed`, and abandoned claims become `interrupted` during startup recovery under the lock. An explicit manual retry may reclaim failed/interrupted/running claims only after obtaining that lock, which proves a previous generator is no longer active. A model request may have been billed before a crash; this is not an exactly-once guarantee for external API calls.

The dashboard reads articles directly from SQLite and the shared deterministic `render_article()` function, not arbitrary filesystem paths. The archive reads only 50 metadata rows per page. It defaults to today's lesson even when only older lessons exist. The approval endpoint calls the existing service without silently accepting editor issues. CLI imports, validation, batches and explicit editor overrides remain available inside the container.

Every article, status and asset route requires HTTP Basic authentication. Only `/healthz` is public and returns a constant liveness result. Mutation requests also require a randomly generated per-process CSRF token obtained from an authenticated page; no CORS access is enabled. A restart invalidates tokens in already-open pages. Hostnames are allowlisted, OpenAPI/docs routes are disabled, private responses are not cached, and CSP prevents scripts or frames from generated text. Only the two bundled JS/CSS files are exposed as assets. There is no file server for `.env`, SQLite, exports or logs.

Copying starts synchronously from the user's button click and writes an article-only `text/html` Blob alongside `text/plain`. Both use the already escaped deterministic content. On unsupported/denied clipboard access, a temporary copy-event handler attempts rich copy, then leaves the article selected with accurate manual-copy instructions. HTTPS or trusted localhost is required for the modern Clipboard API. Authentication and copy compatibility should be tested in the user's target browser and Substack preview.

Compose runs one non-root container with a read-only root filesystem, writable named data/output/log volumes, a small temporary filesystem, dropped capabilities and resource limits. It receives `.env` at runtime; the build context is allowlisted and excludes all credentials and generated data. It binds the configurable port to loopback by default for an existing HTTPS proxy or SSH tunnel. A slim multistage image contains the installed package including templates/assets, but no dev tooling. Rotating application logs persist on their own volume. Do not add multiple replicas/workers or a second host scheduler.

The Dockerfile/Compose contracts, dashboard auth/CSRF/escaping, persistent claim behavior and DST boundary cases have offline tests. Node tests cover both clipboard MIME types and denial fallbacks. A local headless Edge check verified authentication, actual rich HTML clipboard content, approval, archive navigation, empty state and a 390-pixel mobile layout without horizontal overflow. Wheel inspection verified templates and static assets are packaged. No live OpenAI or Substack requests were made. CI includes an actual Docker build and volume-recreation smoke test; Docker was unavailable in the local implementation environment, so that container execution remains to be verified in CI or on the VPS.

## Validation performed during implementation

Offline tests exercise validation, malicious markup escaping, SQLite uniqueness, a competing subprocess lock, export repair after deletion, a seven-day synthetic batch, editor rejection/outage/recovery, correction revisions, local-only publishing, configured timezone dates, SDK call shape and bounded HTTP retries. No real API calls or Substack publication were performed. The bundled example is hand-written; its renderer can be previewed with `scripts/preview_sample.py`.

To extend the schema, add an explicit database migration before changing stored fields. The current code initializes a fresh database but does not migrate arbitrary old schemas. Keep tests offline by injecting a generator or an `httpx.MockTransport`; do not add live API calls to CI.
