"""Loose ad-quote matching (2026-10-12): the ad's own span is returned, never the model's wording."""
from pipeline.agentic.evaluator import _find_in_ad

AD = "About you:\n• Strong Excel skills (PivotTables);\n• A degree in Accounting, Finance or similar.\nApply now."


def test_case_punctuation_and_bullets_resolve_to_the_ads_text():
    assert _find_in_ad("strong excel skills pivottables", AD) == "Strong Excel skills (PivotTables"


def test_ellipsis_quote_uses_its_longest_part():
    assert _find_in_ad("A degree in Accounting, Finance ... Apply", AD) == "A degree in Accounting, Finance"


def test_invented_wording_still_fails():
    assert _find_in_ad("Strong Power BI skills", AD) is None
