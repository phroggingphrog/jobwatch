from types import SimpleNamespace

from pipeline import tracks
from pipeline.category_migration import migrate_legacy


def test_synthetic_legacy_migration_preserves_order_and_policy():
    previous = {"tracks": {"secondary": ["chef"], "drop": ["support"]}, "unlisted": "drop"}
    migration = migrate_legacy(previous, legacy_program_phrases=["graduate", "trainee"])
    cfg = SimpleNamespace(settings={"pipeline": {"screened": migration["migrated"]}})
    snapshot = tracks.settings(cfg)
    assert tracks.classify("Graduate Chef", snapshot) == "undergraduate"
    assert tracks.classify("Support Trainee", snapshot) == "undergraduate"
    assert snapshot.get("secondary").action == "side"
    assert not snapshot.get("secondary").promote
    assert snapshot.get("undergraduate").hours == "allow_hours_only"
    assert tracks.unlisted_drop(cfg)
    assert migration["previous"] == previous
    assert migration["id_mapping"]["primary"] == "primary"
