"""Synthetic characterization of the pre-migration category behavior."""
from types import SimpleNamespace

from pipeline import tracks
from pipeline.category_migration import migrate_legacy


def config(tracks_config=None, **screened):
    old = {"tracks": tracks_config or {}, **screened}
    policy = [dict(id=name,label=name,priority=i,action=action,promote=promote,hours=hours)
        for i,(name,action,promote,hours) in enumerate([
            ('undergraduate','admit',True,'allow_hours_only'),
            ('primary','admit',True,'standard'),('secondary','side',False,'standard'),
            ('drop','archive',False,'standard')])]
    migrated = migrate_legacy(old, legacy_program_phrases=["graduate", "trainee"],
        legacy_policy=policy, program_category='undergraduate',
        id_mapping={p['id']:p['id'] for p in policy})["migrated"]
    return SimpleNamespace(settings={"pipeline": {"screened": migrated}})


def test_legacy_implicit_words_precede_explicit_phrases():
    snapshot = tracks.settings(config({"secondary": ["chef"], "drop": ["support"]}))
    assert tracks.classify("Graduate Chef", snapshot) == "undergraduate"
    assert tracks.classify("IT Support Trainee", snapshot) == "undergraduate"
    assert tracks.classify("Chef", snapshot) == "secondary"
    assert tracks.classify("IT Support", snapshot) == "drop"
    assert tracks.classify("Unrelated title", snapshot) is None


def test_legacy_unlisted_policy_is_explicit():
    assert not tracks.unlisted_drop(config())
    assert tracks.unlisted_drop(config(unlisted="drop"))
