# French A1 Daily Stories

A Python app that prepares one French learning lesson per publication date. It generates a 120–180-word French story, an English translation, vocabulary, a grammar tip, and three questions with answers. Lessons are stored in SQLite and exported as JSON, Markdown and HTML for human review and manual Substack publication. A private, mobile-friendly dashboard lets you browse, review and copy articles directly into Substack.

Start with the instructions below. [CONTEXT.md](CONTEXT.md) explains the implementation and maintenance rules. The original scope is in [FRENCH_SUBSTACK_BUILD_GUIDE.md](FRENCH_SUBSTACK_BUILD_GUIDE.md).

## Docker deployment and private dashboard

On your Ubuntu VPS, use Docker Engine with the Compose plugin. From this project directory:

```bash
cp .env.example .env  # First setup only; preserve an existing .env.
chmod 600 .env
nano .env
# Set OPENAI_API_KEY, DASHBOARD_USERNAME and a unique DASHBOARD_PASSWORD (16+ characters).
docker compose up -d
```

The single container serves the dashboard and generates today's missing lesson at **08:00 London time**, with daylight-saving changes handled automatically. SQLite, articles and rotating application logs live in separate named volumes. A persistent daily job record and the existing database lock prevent duplicate automatic runs. Disable any old cron/systemd schedule for this project before enabling this deployment.

By default the dashboard binds only to the VPS loopback address on port 8080. Open it privately from your computer using:

```bash
ssh -L 8080:127.0.0.1:8080 your-user@your-vps
```

Visit **http://localhost:8080** and enter the credentials from `.env`. For a domain, use your existing HTTPS reverse proxy and add its hostname to `DASHBOARD_ALLOWED_HOSTS`. `DASHBOARD_PORT` is configurable to avoid other apps' ports.

The page shows today's article, a dated archive, validation and approval status, a manual generation button when today's lesson is missing, and **Copy Article** for rich HTML copying. **Mark reviewed** records approval using the existing checks. Substack publication remains manual.

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full DigitalOcean/Ubuntu setup, HTTPS proxy configuration, migration of existing host data, logs, backups, resource limits, failure recovery and updates. The deployment uses one web worker with a 384 MB memory limit and 0.75 CPU limit. Use the CLI instructions below when running without Docker; all CLI commands also work through `docker compose exec app python -m french_bot.cli ...`.

## Install on Windows

Run these commands from this project folder in PowerShell. Python 3.11+ is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python -m pip install --no-deps -e .
Copy-Item .env.example .env
notepad .env
```

Set `OPENAI_API_KEY` in `.env`. Keep `PUBLISH_MODE=local`. The model defaults to the guide's `gpt-4.1-mini`; choose a structured-output model your API account can access if needed. API usage is billed to that account. Existing environment variables take precedence over `.env`.

The setup does not require virtual-environment activation. If `.env` already exists, edit it rather than copying over it. Keys, generated lessons, databases and logs are excluded from Git.

Try the bundled example without an API key:

```powershell
.\.venv\Scripts\python scripts/preview_sample.py
Start-Process .\output\sample\lesson.html
```

This is a hand-written example, not evidence of a live model generation, and it is not added to the database.

Generate your first real lesson:

```powershell
.\.venv\Scripts\python -m french_bot.cli run-daily
```

The command prints the date, review state and folder containing the files. `TZ=Europe/London` determines the date when you omit `--date`.

## Install on Linux / macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
cp .env.example .env
chmod 600 .env
# Edit .env and set OPENAI_API_KEY.
.venv/bin/python -m french_bot.cli run-daily
```

The lockfile pins the environment tested on Windows/Python 3.14. For dependency development, `python -m pip install -e '.[dev]'` resolves the supported ranges instead. Linux and Python 3.11 checks are defined in CI; they have not been run locally on this Windows machine.

## Daily commands

The examples below assume the virtual environment is activated, or that you replace `python` with its full path as above. Run commands from the project root so `.env` and relative paths resolve consistently.

```bash
python -m french_bot.cli generate --date 2026-10-13
python -m french_bot.cli generate --date 2026-10-13
python -m french_bot.cli validate --date 2026-10-13
python -m french_bot.cli validate --date 2026-10-13 --editor
python -m french_bot.cli approve --date 2026-10-13
python -m french_bot.cli publish --date 2026-10-13 --mode local
python -m french_bot.cli list
python -m french_bot.cli run-daily
```

The second `generate` reuses the saved lesson and repairs missing exported files without calling OpenAI. `validate` runs local checks; `--editor` also makes a paid model call. `approve` records your personal review; the app never approves a lesson automatically. `publish --mode local` just exports files and never creates a Substack post or sends email.

Each dated folder contains:

| File | Purpose |
|---|---|
| `lesson.json` | Structured lesson; copy this to make editorial corrections |
| `lesson.md` | Consistent Markdown layout |
| `lesson.html` | Readable browser preview and formatted copy/paste source |
| `review.json` | State, word count, validation/editor findings, model and prompt versions |

`generated` means automated checks passed and human review is still needed. `needs_review` means a check failed. All drafts are exported, including flagged drafts, so you can inspect and fix them. `approved` means you explicitly recorded your review. An AI editor pass cannot establish quality or novelty with certainty.

## Review and publish a lesson

1. Open `output/YYYY-MM-DD/lesson.html` and `review.json`. Check French level, translation completeness, vocabulary, grammar, answers and originality against recent lessons.
2. To correct content, copy `lesson.json` to a separate working file, edit the JSON, and import it:

   ```bash
   python -m french_bot.cli import --date 2026-10-13 --file corrected-lesson.json
   python -m french_bot.cli validate --date 2026-10-13 --editor
   python -m french_bot.cli approve --date 2026-10-13
   ```

   Import preserves the previous database row in a revisions table and resets approval and the old editor verdict. **Editing exported files alone does not update SQLite**; exports are replaced on reruns. Invalid JSON leaves the saved lesson unchanged. Structurally valid JSON with content problems is retained as `needs_review`.

3. If you personally resolve an AI editor disagreement, `approve --accept-editor-issues` records human approval while retaining the editor findings. It cannot override local validation errors.
4. In Substack, create a post, enter the title, and copy the formatted body from the HTML preview (omit the preview's title if you already entered it). Check tables, spacing and answers in Substack's preview, then manually choose publication/scheduling and email settings. Consult the [Substack publishing guide](https://support.substack.com/hc/en-us/articles/360037831771-How-do-I-publish-a-new-post-on-Substack) linked in the original build guide.

The app does not track a manually published remote post as `published`. Remote publication, browser sessions and unattended email are deferred integrations.

## Prepare the first 7 or 30 drafts

```bash
python -m french_bot.cli batch --start 2026-10-13 --days 7
python -m french_bot.cli batch --start 2026-10-13 --days 30
python -m french_bot.cli list
```

The second command resumes the first seven dates and generates only missing dates. It prepares drafts; it does not schedule Substack posts. Review the first seven before generating the full batch. Category rotation uses the most recent 30 stored dates, and the generator/editor see recent scenario summaries. For best editorial continuity, generate dates in increasing order. Future drafts are included in history when backfilling an earlier date.

Batch size is limited to 30 per command. Each new lesson normally takes one generation and one editor request. One content retry can double that; SDK retries on transient API failures can add attempts. A batch stops on an operational failure, retaining completed dates. Flagged lessons do not stop the remaining dates. Resume with the same command.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | empty | Required only when making model calls |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Generation and editor model |
| `TZ` | `Europe/London` | Timezone used for the publication date |
| `DATABASE_PATH` | `./data/stories.sqlite3` | Authoritative SQLite database |
| `OUTPUT_DIR` | `./output` | Rebuildable exported artifacts |
| `PUBLISH_MODE` | `local` | Only implemented publisher in v1 |
| `EDITOR_REVIEW` | `true` | Check new valid drafts with a second model call |
| `INCLUDE_CTA` | `true` | Include the newsletter invitation |
| `OPENAI_TIMEOUT_SECONDS` | `90` | API request timeout |
| `OPENAI_MAX_RETRIES` | `2` | SDK retries after transient failures; range 0–5 |
| `SUBSTACK_PUBLICATION_URL` | empty | Reserved for a future integration; currently unused |

The generation API uses `responses.parse(..., text_format=Lesson)` and `output_parsed`, following the [official OpenAI structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses). Requests set `store=False`.

## Schedule the daily job

**Docker users:** the built-in scheduler already handles this. Do not also install the host schedules below; these are alternatives for CLI-only installations.

On Windows, create a Task Scheduler task under your Windows account. Set a daily trigger, use the project directory as **Start in**, and set:

- Program: `C:\Workspace\substack-learn\.venv\Scripts\python.exe`
- Arguments: `-m french_bot.cli run-daily`

The trigger follows the computer's scheduling timezone. `TZ` determines the lesson date, not the Task Scheduler trigger time. The PowerShell wrapper in `scripts/run_daily.ps1` is also available for manual or scheduled use.

For Linux cron:

```bash
chmod +x scripts/run_daily.sh
crontab -e
```

```cron
0 8 * * * /opt/french-story-bot/scripts/run_daily.sh
```

The wrapper finds the project relative to itself and appends output to `daily.log`. Cron's 08:00 is **server local time**. For 08:00 London time across daylight-saving changes, use the provided systemd timer instead:

1. Install the project and `.venv` at `/opt/french-story-bot`. Create a dedicated `frenchbot` account, or edit `User=` to an existing account that owns the project and can write its `data/` and `output/` directories.
2. Copy `scripts/french-story-bot.service` and `.timer` into `/etc/systemd/system/`; adjust paths and account if needed.
3. Run:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now french-story-bot.timer
   systemctl list-timers french-story-bot.timer
   journalctl -u french-story-bot.service
   ```

Use one scheduler. `Persistent=true` runs a missed timer once after restart; it does not backfill every missed date. Use `batch` for deliberate backfills. These setup steps do not install or enable a scheduler automatically.

## Failures, recovery and backups

Exit codes are `0` for successful operation, `1` for an operational/configuration failure, and `2` when a processed lesson needs review. Monitor nonzero exits with your scheduler or monitoring service. No notification credentials or outbound alert integration are configured in v1.

- Missing key or HTTP 401: set/check the API key. HTTP 403/404: check model access. HTTP 429: inspect API quota/rate limits. Connection/5xx errors receive bounded SDK retries.
- Editor unavailable: the generated content is retained with `needs_review`. Run `validate --editor`, or personally review and explicitly accept the editor issue.
- Another process holds the lock: wait for it to finish and rerun. Locks release when a process exits; a remaining `.lock` file alone does not mean the database is busy. Do not delete the lock file while a job is running.
- Interrupted export: rerun `generate` for that date. SQLite is committed first; files are atomically replaced individually and rebuilt from it. A folder can briefly contain files from different revisions if export is interrupted.
- Failed content checks: inspect `review.json`, correct via `import`, validate and approve. Rerunning `generate` intentionally does not replace an existing flagged lesson or incur another generation charge.

Back up the SQLite database and `.env` securely. Stop the scheduler and wait for active commands to finish before copying the database, or use SQLite's backup API. Preserve database backups separately from the generated files. Losing the database loses the idempotency and approval history. Keep each deployment's database/output pair together; this is a single-host app, not a distributed worker system.

## Development checks

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
node --test tests/test_copy.cjs
```

Tests run without API keys or external requests. They cover seven dated synthetic responses, validation, safe rendering, editor recovery, import revisions, cross-process locking, rerun recovery, API retries and the CLI. They do not certify the quality of seven or thirty live model-generated lessons. Those still need the real API and human review.
