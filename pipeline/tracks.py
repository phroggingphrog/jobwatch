"""Per-user title categories for screened discovery."""
from __future__ import annotations

import re

from .category_snapshot import CategorySnapshot

HOURS_REASONS = frozenset({"hours_exceeded", "advertised_hours", "full_time_only"})


def settings(config) -> CategorySnapshot:
    own = (((getattr(config, "settings", None) or {}).get("pipeline") or {}).get("screened") or {})
    return CategorySnapshot.model_validate(own.get("category_snapshot") or {})


def unlisted_drop(config) -> bool:
    own = (((getattr(config, "settings", None) or {}).get("pipeline") or {}).get("screened") or {})
    return own.get("unlisted_action") == "archive"


def classify(title: str, snapshot: CategorySnapshot) -> str | None:
    text = (title or "").casefold()
    for category in snapshot.ordered():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text)
               for phrase in category.phrases):
            return category.id
    return None
