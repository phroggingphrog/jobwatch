"""Suburb-only Victorian locations (ABS SAL 2021, VIC-unique names) pass the location rule."""
import yaml
from jobwatch.filters import Rules
from jobwatch.models import Posting

RULES = Rules(yaml.safe_load(open("config/rules.yaml")))


def _p(loc):
    return Posting(source="t", source_id="1", url="https://x/1", title="Customer Service Officer",
                   company="Acme", location=loc)


def test_vic_unique_suburb_passes():
    assert RULES.location_rule(_p("Telstra Store Caroline Springs")) == "vic_locality"


def test_other_state_named_blocks_locality():
    assert RULES.location_rule(_p("Richmond NSW")) is None
    assert RULES.location_rule(_p("Sydney")) is None


def test_ambiguous_name_alone_is_not_enough():
    # Richmond and Brighton exist in several states, so a bare name doesn't count.
    assert RULES.location_rule(_p("Brighton")) is None
