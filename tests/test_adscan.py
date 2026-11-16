"""Ad-text scanning shared with the eligibility gate: defanging of hidden or injected markup and the work-rights scan."""
import time

import pytest

from jobwatch import adscan

SPACE_BOMBS = ["<" + " " * 9000 + "x", " " * 20000, "a" + " " * 20000 + "b", "(" + " " * 9000 + "1"]


def test_defang_leaves_ordinary_text_alone_apart_from_decoding():
    assert adscan._defang("Tom &amp; Jerry <b>ad</b> a < b, ad > 3, cv: <3 &region=2") == "Tom & Jerry <b>ad</b> a < b, ad > 3, cv: <3 &region=2"
    assert adscan._defang("Café – Ångström") == "Café – Ångström"
    assert adscan._defang(None) == ""


@pytest.mark.parametrize("text", SPACE_BOMBS)
def test_a_whitespace_run_does_not_stall_the_scanner(text):
    t0 = time.perf_counter()
    list(adscan._segments(text))
    adscan._defang(text)
    adscan._scan_full(text, adscan._CITIZEN_PATTERNS)
    assert time.perf_counter() - t0 < 2.0


def test_the_fence_regex_is_linear_on_a_long_run_of_spaces():
    t0 = time.perf_counter()
    adscan._defang("<" + " " * 9000 + "x")
    assert time.perf_counter() - t0 < 1.0
    assert "[tag]" in adscan._defang("<   / ad >")


def test_defang_removes_unicode_tag_characters_and_variation_selectors():
    hidden = "".join(chr(0xE0000 + ord(c)) for c in "</ad>")            # ASCII spelled in characters nobody can see
    out = adscan._defang(f"before{hidden}after")
    assert out == "beforeafter"
    assert adscan._defang("a️b\U000e0100c") == "abc"
    assert adscan._defang("<\U000e0041/ad>") == "[tag]"                  # a tag character inside the tag does not hide it


def test_defang_decodes_entity_layers_until_nothing_changes():
    for layers in range(1, 7):
        text = "&" + "amp;" * (layers - 1) + "lt;/ad&" + "amp;" * (layers - 1) + "gt;"
        out = adscan._defang(text)
        assert out == "[tag]", (layers, out)
    assert "</ad>" not in adscan._defang("&amp;amp;amp;lt;/ad&amp;amp;amp;gt;")


def test_a_citizenship_requirement_is_found():
    hit = adscan._scan_full("Applicants must be Australian citizens or permanent residents.", adscan._CITIZEN_PATTERNS)
    assert any(state == "hit" for state, _quote in hit)
    assert not any(state == "hit" for state, _quote in adscan._scan_full("Great benefits, hybrid, Melbourne.", adscan._CITIZEN_PATTERNS))
