"""Deterministic least-recently-used category rotation."""

from dataclasses import dataclass

CATEGORIES = (
    "daily life",
    "food",
    "family",
    "commuting",
    "travel",
    "shopping",
    "hobbies",
    "school",
    "weather",
    "social interactions",
    "work",
)


@dataclass(frozen=True)
class HistoryItem:
    publication_date: str
    category: str
    title: str
    topic: str
    summary: str


def choose_category(history: list[HistoryItem]) -> str:
    """History is newest first. Unseen categories win, then the oldest category."""
    recent_positions = {}
    for index, item in enumerate(history):
        recent_positions.setdefault(item.category, index)
    return max(CATEGORIES, key=lambda category: recent_positions.get(category, len(history) + 1))
