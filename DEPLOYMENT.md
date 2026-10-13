# Ubuntu / DigitalOcean deployment

This deployment adds one container alongside your existing applications. It runs the dashboard and one background generator, uses no Redis or separate database, and binds port 8080 to the VPS loopback interface by default. Three named Docker volumes retain the database, articles and application logs across container replacement.

## 1. Prepare the VPS

Use an existing Docker Engine installation with the Docker Compose plugin. Check:

```bash
docker --version
docker compose version
```

If missing, follow [Docker's official Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/). Do not replace your existing reverse proxy or other applications. Choose a free directory, for example `/opt/french-story-bot`, and copy/clone this repository there. Use the same directory and Compose project name on later deployments so Compose reconnects the same volumes.

```bash
cd /opt/french-story-bot
cp .env.example .env  # Only on first setup; preserve an existing .env.
chmod 600 .env
nano .env
```

Set these values:

```dotenv
OPENAI_API_KEY=your-api-key
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD='your-long-unique-random-password'
DASHBOARD_ALLOWED_HOSTS=localhost,127.0.0.1
DASHBOARD_PORT=8080
DASHBOARD_BIND_ADDRESS=127.0.0.1
```

Use at least 16 characters for the password; a password manager can generate one. Single quotes around a password in `.env` preserve literal `$` and `#` characters. The app refuses to start without dashboard credentials. `.env` is excluded from Git and from the Docker build context. Compose supplies it at runtime; Docker administrators can inspect container environment variables, so protect both the file and Docker access. Do not paste the output of `docker compose config` (without `--quiet`) or `docker inspect` into public logs.

`DASHBOARD_PORT` can be changed if 8080 is already in use. Compose fixes the container's database/output/log paths and `TZ=Europe/London` so the scheduler and dashboard use the same persistent storage and publication date. Existing host cron or systemd jobs for this project must be disabled before using the built-in scheduler. Keep one replica and one Uvicorn worker.

## 2. Start

```bash
docker compose config --quiet
docker compose up -d
docker compose ps
```

The image builds on the first run. `restart: unless-stopped` restarts the container after process failure or a Docker/VPS restart, unless you explicitly stopped it. Docker's health check reports HTTP responsiveness; Docker Compose does not automatically restart a merely unhealthy but still-running container.

The configuration caps the app at 384 MB RAM, 0.75 CPU and 80 processes/threads. It uses a slim Python image, one worker and a dependency-free browser UI. This leaves some room on a 1 GB VPS for your other apps, but actual headroom depends on their load. Check `docker stats --no-stream` after generation. If building alongside existing workloads exhausts RAM, build this same image on another machine/CI and transfer it to the VPS, rather than increasing the running app's limits blindly.

## 3. Open your private dashboard

For private access without a public domain, create an SSH tunnel from your computer:

```bash
ssh -L 8080:127.0.0.1:8080 your-user@your-vps
```

Keep that terminal open, visit **http://localhost:8080**, and enter the dashboard username/password when the browser asks. If local port 8080 is occupied, use `-L 8081:127.0.0.1:8080` and visit localhost:8081. Adjust the remote port if you changed `DASHBOARD_PORT`.

For a public HTTPS address, point a subdomain such as `french.example.com` to your VPS, add it to `DASHBOARD_ALLOWED_HOSTS`, and route that hostname through your existing reverse proxy. Keep the app bound to 127.0.0.1. Use an HTTPS certificate from your existing certificate manager.

Example location inside an existing **HTTPS Nginx server block** for that subdomain:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_http_version 1.1;
}
```

This is a location snippet, not a complete certificate configuration. Preserve your other server blocks and validate with `sudo nginx -t` before reloading Nginx. If your reverse proxy is itself containerized, attach this app to its private Docker network and proxy to `app:8080` on that network; loopback inside a separate proxy container is not the VPS loopback. Do not expose raw HTTP on a public interface. Basic authentication needs encrypted transport, and browsers restrict modern [rich clipboard writes to secure contexts](https://developer.mozilla.org/en-US/docs/Web/API/Clipboard/write) (HTTPS or trusted localhost).

After changing `.env`, run `docker compose up -d --force-recreate`. A plain container restart does not reload changed Compose environment values.

## 4. Review and copy

The page opens on today's London date. If no lesson exists, click **Generate today’s lesson**; the work runs in a background thread while the page stays responsive. It refreshes when the article is saved. If generation failed or was interrupted, the page shows a short message and permits an explicit retry.

Select older lessons in **Previous articles**. Review the validation and approval badges, read **Review details**, and click **Mark reviewed** to record approval when checks allow it. If checks fail, use the existing CLI correction/import and approval commands below; the dashboard does not silently override editor concerns.

**Copy Article** copies only the article, including its heading, bold text, lists and table, in both `text/html` and `text/plain`. It excludes the dashboard buttons, badges and review notes. Paste into the body of a Substack draft. The article includes the title, so remove that body heading if you enter the same title in Substack's title field. Confirm Substack's preview before manually publishing or scheduling. Browser/editor paste behavior can vary; no Substack automation is involved.

If one-click copying is blocked, the app tries a legacy rich copy. If that also fails, it selects the article and tells you to use Ctrl+C / Cmd+C or the mobile Copy action. It does not claim a successful rich copy after a failed attempt. Browser Basic Auth credentials are cached by the browser; closing the browser/private window is the simplest way to end that session.

## Daily scheduling and duplicate prevention

The built-in scheduler checks every 30 seconds and starts today's missing lesson at or just after **08:00 Europe/London**, including DST changes. Starting the container after 08:00 catches up today's missing lesson once; it does not generate all dates missed while the VPS was off. A manually generated lesson before 08:00 is reused.

The dashboard, scheduler and CLI share the same SQLite database and OS file lock. A `generation_runs` table records a claim before calling the model. Restarting, repeated scheduler ticks and duplicate clicks do not start another automatic attempt for a claimed date. Successful lessons retain the existing unique publication-date constraint. One ordinary generation attempt can still perform the pipeline's original single content retry and bounded SDK retries.

A failed attempt is **not** automatically repeated every 30 seconds. On restart, an abandoned running claim becomes `interrupted`. Check for saved content first; then explicitly retry through the dashboard if today's article is still missing. No system can guarantee a model request wasn't billed immediately before a process crash; an explicit retry can make another API request. Only one saved lesson per date is allowed.

## CLI access and existing data

Every existing CLI command is available inside the container, using the shared volumes:

```bash
docker compose exec app python -m french_bot.cli list
docker compose exec app python -m french_bot.cli validate --date 2026-10-13 --editor
docker compose exec app python -m french_bot.cli approve --date 2026-10-13
docker compose exec app python -m french_bot.cli batch --start 2026-10-13 --days 7
```

For corrections, copy edited lesson JSON into the existing output volume and import it:

```bash
docker compose cp corrected-lesson.json app:/app/output/corrected-lesson.json
docker compose exec app python -m french_bot.cli import --date 2026-10-13 --file /app/output/corrected-lesson.json
```

The image's code filesystem is read-only. Use `/app/output` for working files. A CLI command returns a lock error if another job is active; wait and rerun. CLI commands keep their original behavior, including same-date reuse, and are explicit operator actions rather than automatic scheduled retries.

**Existing host data is not automatically copied into new named volumes.** To migrate, first stop the old scheduler and wait for any active generator. Before starting the new dashboard, copy the database (and optionally exports) into the new volumes:

```bash
docker compose build
docker compose run --rm --no-deps --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE \
  -v "$PWD/data:/import-data:ro" -v "$PWD/output:/import-output:ro" \
  --entrypoint sh app -c 'cp /import-data/stories.sqlite3 /app/data/stories.sqlite3 && cp -a /import-output/. /app/output/ && chown -R 10001:10001 /app/data /app/output'
docker compose up -d
```

Take a backup first. This migration replaces the destination database, so use it only for the initial move into empty volumes. The old `.lock` file is not copied. The new job table is created automatically without changing existing lesson rows. If there are no prior exports, omit the `/import-output` mount and the `cp -a` command. Existing articles are rendered from SQLite even if exports are missing.

## Logs, upgrades and backups

```bash
docker compose logs --tail=100 app
docker compose exec app tail -n 100 /app/logs/application.log
docker stats --no-stream
```

Lifecycle/server logs use Docker's rotating log driver (three 2 MB files). Generation and application logs are persisted in the `stories_logs` volume (one active plus three rotated 2 MB files). Request access logs are disabled. Secrets and raw API exception bodies are not logged by the generation worker.

To deploy an update, back up first, pull/copy the new code, then:

```bash
docker compose up -d --build
```

To back up consistently without racing a generator, stop the app, copy the persistent directories from the stopped container, then start it again:

```bash
backup_dir="backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
docker compose stop app
docker compose cp app:/app/data "$backup_dir/data"
docker compose cp app:/app/output "$backup_dir/output"
docker compose cp app:/app/logs "$backup_dir/logs"
docker compose start app
```

Keep `.env` in a separate protected backup. `docker compose down` preserves named volumes; **`docker compose down -v` deletes them**. For restore, stop the app and use a one-off `docker compose run --no-deps --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE` container as in the migration example, mounting the backup directories instead. Ensure restored directories are owned by UID/GID 10001 and use the same Compose project/directory.

## Local development and checks

```bash
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
# Configure dashboard credentials in .env; set SCHEDULER_ENABLED=false for UI-only development.
python -m uvicorn french_bot.dashboard:create_app --factory --host 127.0.0.1 --port 8080 --workers 1
python -m pytest -q
node --test tests/test_copy.cjs
```

Node 18+ is needed only for the clipboard unit tests, not the Docker image or runtime dashboard. The tests use synthetic lessons and never call OpenAI. CI adds a Linux Docker build, authenticated HTTP smoke test and volume persistence check. The implementation environment did not have Docker installed, so that image build and live container check must run in CI or on your VPS; local tests cover the Compose structure and Dockerfile contract.
