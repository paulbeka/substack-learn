"""One lightweight worker; London wall-clock scheduling and durable daily claims."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from zoneinfo import ZoneInfo

from filelock import Timeout

from .config import Settings
from .service import LessonService
from .storage import Storage

log = logging.getLogger(__name__)
LONDON = ZoneInfo("Europe/London")


def due_date(now: datetime) -> str | None:
    """At/after 08:00 London, catch up today only; UTC offset follows DST."""
    local = now.astimezone(LONDON)
    return local.date().isoformat() if local.hour >= 8 else None


class GenerationRunner:
    def __init__(self, settings: Settings, storage: Storage, service_factory=LessonService):
        self.settings, self.storage, self.service_factory = settings, storage, service_factory
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lesson-generator")
        self.guard = Lock()
        self.future = None
        self.notice = ""

    @property
    def busy(self):
        return self.future is not None and not self.future.done()

    def submit(self, day: str, manual: bool = False) -> bool:
        with self.guard:
            if self.busy:
                return False
            self.notice = "Generation requested."
            self.future = self.executor.submit(self.run, day, manual)
            return True

    def run(self, day: str, manual: bool = False):
        try:
            with self.storage.lock:
                if self.storage.get(day):
                    self.notice = "The article is already saved."
                    return
                if not self.storage.claim_run(day, manual):
                    self.notice = "Today's attempt is already recorded. Review its status below."
                    return
                try:
                    service = self.service_factory(self.settings, self.storage)
                    service.generate(day)
                    record = service.validate(day)
                    self.storage.finish_run(
                        day, "succeeded", "Article saved: " + record.status + "."
                    )
                    self.notice = "Article saved."
                    log.info("date=%s scheduled_generation=complete status=%s", day, record.status)
                except Exception as exc:  # noqa: BLE001 -- never log model/credential-bearing bodies.
                    self.notice = (
                        "Generation failed. Check configuration and logs, then retry manually."
                    )
                    self.storage.finish_run(day, "failed", self.notice)
                    log.error("date=%s generation_failed error_type=%s", day, type(exc).__name__)
        except Timeout:
            self.notice = (
                "Another command is generating or editing a lesson. Try again after it finishes."
            )
        except Exception as exc:  # noqa: BLE001 -- worker boundary must not leak secrets.
            self.notice = "Storage is unavailable. Check the service logs."
            log.error("date=%s worker_failed error_type=%s", day, type(exc).__name__)

    async def schedule(self):
        while True:
            try:
                day = due_date(datetime.now(LONDON))
                if day and not self.storage.get(day) and not self.storage.run_status(day):
                    self.submit(day)
            except Exception as exc:  # noqa: BLE001 -- keep the scheduler alive after storage errors.
                log.error("scheduler_failed error_type=%s", type(exc).__name__)
            await asyncio.sleep(30)

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
