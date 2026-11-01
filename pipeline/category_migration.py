"""Build explicit legacy policy data without reading or writing live settings."""
from __future__ import annotations

from copy import deepcopy

from .category_snapshot import CategorySnapshot


def migrate_legacy(screened: dict, *, legacy_program_phrases: list[str]) -> dict:
    """Return a reversible plan. The caller supplies the legacy code vocabulary.

    Preserve the input independently so an operator can restore it with the old
    application revision. Activation and backups belong to the release owner.
    """
    old = deepcopy(screened)
    lists = old.get("tracks") or {}
    policy = (
        ("undergraduate", "admit", True, "allow_hours_only"),
        ("primary", "admit", True, "standard"),
        ("secondary", "side", False, "standard"),
        ("drop", "archive", False, "standard"),
    )
    categories = []
    for priority, (key, action, promote, hours) in enumerate(policy):
        words = list(lists.get(key) or [])
        if key == "undergraduate":
            words = list(legacy_program_phrases) + words
        categories.append({"id": key, "label": key, "priority": priority, "phrases": words,
                           "action": action, "promote": promote, "hours": hours})
    snapshot = CategorySnapshot.model_validate({"categories": categories})
    result = deepcopy(old)
    result.pop("tracks", None)
    unlisted = result.pop("unlisted", "keep")
    result["unlisted_action"] = "archive" if str(unlisted).casefold() == "drop" else "admit"
    result["category_snapshot"] = snapshot.model_dump(mode="json")
    return {"previous": old, "migrated": result, "id_mapping": {item[0]: item[0] for item in policy}}
