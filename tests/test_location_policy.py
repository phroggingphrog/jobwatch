"""Person-independent region and commute evidence (no fixed home state)."""
import hashlib
from importlib.resources import files

import pytest

from pipeline.agentic import location
from pipeline.agentic.location import commute_km_for, location_verdict, regions_named


@pytest.mark.parametrize('text,expect', [
    ('Sydney NSW', {'NSW'}), ('Parramatta, New South Wales', {'NSW'}), ('Melbourne, VIC; Sydney, NSW', {'VIC', 'NSW'}),
    ('Box Hill campus', {'VIC'}), ('Richmond NSW', {'NSW'}), ('Perth WA', {'WA'}), ('Remote, Australia wide', set()),
    ('Level 3, 1 Example St', set()), ('Sydney Road, Brunswick VIC', {'VIC'}), ('Victoria Street, Sydney NSW', {'NSW'}),
    ('Adelaide Street, Brisbane QLD', {'QLD'}), ('Victoria Street, Melbourne', {'VIC'})])
def test_regions_named(text, expect):
    assert regions_named(text) == frozenset(expect)


@pytest.mark.parametrize('quote,regions,remote_fit,remote_ok,expect', [
    ('Sydney NSW', {'NSW'}, False, None, 'in'), ('Sydney NSW', {'VIC'}, False, None, 'outside'),
    ('Melbourne VIC or Sydney NSW', {'VIC'}, False, None, 'in'),
    ('Work from home anywhere in Australia', {'VIC'}, True, None, 'remote'),
    ('Remote, Sydney NSW', {'VIC'}, True, False, 'outside'),
    ('Level 3, 1 Example St', {'VIC'}, False, None, 'unknown'), ('Anywhere', set(), False, None, 'in')])
def test_location_verdict(quote, regions, remote_fit, remote_ok, expect):
    assert location_verdict(quote, frozenset(regions), remote_fit=remote_fit, remote_ok=remote_ok) == expect


def test_commute_km_for_uses_victorian_data_only():
    assert 5 <= commute_km_for('Box Hill, VIC', 'Carlton VIC') <= 20
    assert commute_km_for('Box Hill, VIC', 'Sydney NSW') is None and commute_km_for(None, 'Carlton VIC') is None
    assert commute_km_for('Sydney NSW', 'Carlton VIC') is None
    assert commute_km_for('Box Hill, VIC', 'Richmond NSW') is None


@pytest.mark.parametrize('other', ['Richmond NSW', 'Victoria Street, Richmond NSW', 'Melbourne Rd, Richmond NSW',
                                   'Richmond nsw', 'Richmond N.S.W.', 'Richmond New South Wales'])
def test_commute_km_for_withholds_distance_when_another_state_is_named(other):
    assert commute_km_for('Box Hill, VIC', other) is None
    assert commute_km_for(other, 'Carlton VIC') is None
    assert 5 <= commute_km_for('Box Hill, VIC', 'Carlton VIC') <= 20


def test_existing_location_reference_hash_is_unchanged():
    assert location.LOCATION_REFERENCE_HASH == hashlib.sha256(
        files('pipeline.agentic').joinpath('data/metro-localities.json').read_bytes()).hexdigest()
