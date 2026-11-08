"""Suburb-only Victorian locations (ABS SAL 2021, VIC-unique names) pass the location rule."""
import yaml
from jobwatch.filters import Rules
from jobwatch.models import Posting

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
RULES = Rules({
    "location": {
        "vic_patterns": [r"\bmelbourne\b", r"\bvic\b"],
        "remote_patterns": [r"\bremote\b"],
        "other_state_patterns": [r"\bnsw\b", r"\bsydney\b"],
        "vic_localities_file": str(FIXTURES / "vic_localities_test.txt"),
    },
})


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
