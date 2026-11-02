"""Explicit legacy data preserve old decisions; runtime has no program defaults."""
from types import SimpleNamespace

from pipeline import tracks
from pipeline.category_migration import migrate_legacy


def test_explicit_legacy_policy_preserves_admin_clerical_and_program_order():
    policy=[dict(id=name,label=name,priority=i,action=action,promote=promote,hours=hours)
        for i,(name,action,promote,hours) in enumerate([
            ('programs','admit',True,'allow_hours_only'),
            ('career','admit',True,'standard'),('income','side',False,'standard'),
            ('excluded','archive',False,'standard')])]
    previous={'tracks':{'career':['administrative','clerical'],'income':['chef'],'excluded':['nurse']},'unlisted':'drop'}
    migration=migrate_legacy(previous,legacy_program_phrases=['graduate','intern'],
        legacy_policy=policy,program_category='programs',id_mapping={p['id']:p['id'] for p in policy})
    cfg=SimpleNamespace(settings={'pipeline':{'screened':migration['migrated']}})
    snapshot=tracks.settings(cfg)
    for title,expected in [('Administrative Assistant','career'),('Clerical Officer','career'),
                           ('Graduate Chef','programs'),('Chef','income'),('Nurse','excluded')]:
        assert tracks.classify(title,snapshot)==expected
    assert tracks.unlisted_drop(cfg)
    assert snapshot.get('programs').hours=='allow_hours_only'
    assert snapshot.get('career').promote is True
    assert snapshot.get('income').promote is False
    assert snapshot.get('excluded').action=='archive'
    assert migration['previous']==previous


def test_empty_snapshot_is_neutral_even_with_stale_unlisted_setting():
    cfg=SimpleNamespace(settings={'pipeline':{'screened':{'unlisted_action':'archive'}}})
    assert not tracks.unlisted_drop(cfg)
    assert tracks.classify('Graduate Administrative Assistant',tracks.settings(cfg)) is None
