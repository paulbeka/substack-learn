"""Publication boundary. Local export never means a remote post was published."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .storage import Storage, StoredLesson


@dataclass(frozen=True)
class PublishResult:
    status: str
    output_path: Path
    remote_id: str | None = None
    remote_url: str | None = None


class Publisher(Protocol):
    def publish(self, lesson: StoredLesson) -> PublishResult: ...


class LocalPublisher:
    def __init__(self, storage: Storage, include_cta: bool = True):
        self.storage = storage
        self.include_cta = include_cta

    def publish(self, lesson: StoredLesson) -> PublishResult:
        return PublishResult("local_export", self.storage.export(lesson, self.include_cta))


def get_publisher(mode: str, storage: Storage, include_cta: bool = True) -> Publisher:
    if mode != "local":
        raise ValueError("Only local export is implemented. Publish manually in Substack.")
    return LocalPublisher(storage, include_cta)
