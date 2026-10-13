"""Private single-user dashboard. Serve with one Uvicorn worker and HTTPS upstream."""

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from filelock import Timeout
from markupsafe import Markup
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .cli import RedactSecrets
from .config import ConfigurationError, Settings, boolean
from .render import render_article
from .scheduler import GenerationRunner
from .service import LessonService
from .storage import Storage

ASSETS = Path(__file__).parent


@dataclass(frozen=True)
class DashboardSettings:
    username: str
    password: str = field(repr=False)
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    scheduler_enabled: bool = True
    log_dir: Path = Path("logs")

    @classmethod
    def from_env(cls):
        username = os.getenv("DASHBOARD_USERNAME", "").strip()
        password = os.getenv("DASHBOARD_PASSWORD", "")
        if not username or len(password) < 16 or ":" in username:
            raise ConfigurationError(
                "Set DASHBOARD_USERNAME and a DASHBOARD_PASSWORD of at least 16 characters."
            )
        hosts = tuple(
            item.strip()
            for item in os.getenv("DASHBOARD_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
            if item.strip()
        )
        if not hosts or "*" in hosts:
            raise ConfigurationError("DASHBOARD_ALLOWED_HOSTS must list specific hostnames.")
        return cls(
            username,
            password,
            hosts,
            boolean("SCHEDULER_ENABLED", True),
            Path(os.getenv("LOG_DIR", "./logs")),
        )


def setup_logging(settings: Settings, dashboard: DashboardSettings):
    dashboard.log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        dashboard.log_dir / "application.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler.addFilter(RedactSecrets(settings.api_key))
    handler.addFilter(RedactSecrets(dashboard.password))
    logger = logging.getLogger("french_bot")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("openai").setLevel(logging.CRITICAL)
    return logger, handler


def canonical_day(value: str) -> str:
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
        return value
    except ValueError:
        raise HTTPException(400, "Use a date in YYYY-MM-DD format.") from None


def create_app(settings: Settings | None = None, dashboard: DashboardSettings | None = None):
    settings = settings or Settings.from_env()
    dashboard = dashboard or DashboardSettings.from_env()
    storage = Storage(settings.database_path, settings.output_dir)
    runner = GenerationRunner(settings, storage)
    csrf_token = secrets.token_urlsafe(32)
    templates = Jinja2Templates(directory=ASSETS / "templates")

    @asynccontextmanager
    async def lifespan(app):
        logger, handler = setup_logging(settings, dashboard)
        try:
            with storage.lock:
                storage.recover_runs()
        except Timeout:
            logger.info("Startup recovery deferred: another generator holds the lock.")
        task = asyncio.create_task(runner.schedule()) if dashboard.scheduler_enabled else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await asyncio.to_thread(runner.close)
            logger.removeHandler(handler)
            handler.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.storage, app.state.runner = storage, runner
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(dashboard.allowed_hosts))
    basic = HTTPBasic()

    def authenticate(credentials: Annotated[HTTPBasicCredentials, Depends(basic)]):
        user_ok = secrets.compare_digest(credentials.username.encode(), dashboard.username.encode())
        password_ok = secrets.compare_digest(
            credentials.password.encode(), dashboard.password.encode()
        )
        if not (user_ok & password_ok):
            raise HTTPException(
                401,
                "Authentication required.",
                headers={"WWW-Authenticate": 'Basic realm="French Stories"'},
            )

    def mutation(request: Request, _: Annotated[None, Depends(authenticate)]):
        if not secrets.compare_digest(
            request.headers.get("X-CSRF-Token", "").encode(), csrf_token.encode()
        ):
            raise HTTPException(403, "Refresh the dashboard and try again.")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                "Permissions-Policy": "clipboard-write=(self)",
            }
        )
        return response

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/", dependencies=[Depends(authenticate)])
    def index(request: Request, day: str | None = None, page: int = 1):
        if page < 1 or page > 100000:
            raise HTTPException(400, "Invalid archive page.")
        today = settings.today().isoformat()
        selected = canonical_day(day) if day else today
        record = storage.get(selected)
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "today": today,
                "selected": selected,
                "record": record,
                "article": Markup(render_article(record.lesson, settings.include_cta))
                if record
                else "",
                "archive": storage.archive(page),
                "page": page,
                "csrf_token": csrf_token,
                "job": storage.run_status(today),
                "busy": runner.busy,
            },
        )

    @app.get("/assets/{name}", dependencies=[Depends(authenticate)])
    def asset(name: str):
        if name not in {"dashboard.css", "dashboard.js"}:
            raise HTTPException(404)
        return FileResponse(ASSETS / "static" / name)

    @app.get("/api/status", dependencies=[Depends(authenticate)])
    def status():
        today = settings.today().isoformat()
        return {
            "today": today,
            "exists": storage.get(today) is not None,
            "busy": runner.busy,
            "job": storage.run_status(today),
            "notice": runner.notice,
        }

    @app.post("/api/generate", dependencies=[Depends(mutation)])
    def generate():
        day = settings.today().isoformat()
        if storage.get(day):
            return {"message": "Today's article already exists.", "exists": True}
        if not runner.submit(day, manual=True):
            raise HTTPException(409, "A generation is already in progress.")
        return JSONResponse(
            {"message": "Generation started. This page will update when ready."}, status_code=202
        )

    @app.post("/api/approve/{day}", dependencies=[Depends(mutation)])
    def approve(day: str):
        day = canonical_day(day)
        try:
            with storage.lock:
                LessonService(settings, storage).approve(day)
        except Timeout:
            raise HTTPException(
                409, "Another job is active. Try again after it finishes."
            ) from None
        except ValueError:
            raise HTTPException(
                409,
                "Approval requires resolved checks. Review the findings and use the CLI to correct the lesson or explicitly accept editor concerns.",
            ) from None
        return {"message": "Review recorded. Article approved."}

    return app
