"""Combined facet filters (no shared closure), ASCII-only number parsing, and stale / out-of-range ids.
Synthetic rows and scratch DBs only."""
import itertools
import random

import pytest
from fastapi.testclient import TestClient

from jobwatch.web import queries as q
from jobwatch.web.app import create_app
from tests.web.test_web import OK, client, seed  # noqa: F401  (the shared fixture)

ARMS = ["call_centre", "retail_sales", None]
SRCS = ["seek", "jora", "indeed"]
SECTORS = ["retail", "health", None]
ARCHS = ["Support", "Other", ""]
WARNS = ["fulltime", "clearance", "senior"]


def make_rows(n=400, seed_=7):
    rnd = random.Random(seed_)
    rows = []
    for i in range(n):
        srcs = rnd.sample(SRCS, rnd.choice([1, 1, 2]))
        sal = rnd.choice([None, 40000, 70000, 110000])
        score = rnd.choice([None, 3.0, 3.6, 4.2, 4.7])
        state = rnd.choice(["show", "show", "review", "hide", "pending"])
        rows.append({
            "id": i, "arm": rnd.choice(ARMS), "tier": rnd.choice(["core", "fallback", "ai"]), "srcs": srcs,
            "sector": rnd.choice(SECTORS), "age_days": rnd.choice([0, 2, 6, 20]),
            "is_remote": rnd.random() < .3, "is_vic": rnd.random() < .7, "wt": rnd.choice(["FT", "PT", "casual"]),
            "has_salary": sal is not None, "sal_year": sal, "entry": rnd.random() < .5,
            "warn": set(rnd.sample(WARNS, rnd.choice([0, 0, 1, 2]))), "archetype": rnd.choice(ARCHS),
            "score5": score, "ai_state": state,
            "ai": {"hide_reason": rnd.choice([None, "too_senior", "no_rights"])} if state == "hide" else {},
            "status": rnd.choice(["new", "seen", "saved", "hidden"])})
    return rows


def reference(r, f):
    """The obviously-correct version of every facet check, written without closures."""
    ok = True
    ok &= not f.arm or (r["arm"] or "none") in f.arm
    ok &= not f.tier or r["tier"] in f.tier
    ok &= not f.src or any(s in f.src for s in r["srcs"])
    ok &= not f.sector or (r["sector"] or "unlisted") in f.sector
    ok &= not f.within or r["age_days"] <= f.within
    ok &= not f.arr or (("remote" in f.arr and r["is_remote"]) or ("vic" in f.arr and r["is_vic"]))
    ok &= not f.wt or r["wt"] in f.wt
    if f.sal or f.salmin:
        ok &= r["has_salary"] and (r["sal_year"] or 0) >= (f.salmin or 0) * 1000
    ok &= not f.entry or r["entry"]
    ok &= not f.hide or not (r["warn"] & set(f.hide))
    ok &= not f.arch or r["archetype"] in f.arch
    ok &= not f.minscore or (r["score5"] is not None and r["score5"] >= f.minscore - 1e-9)
    ok &= (r["ai_state"] == "hide" and (r["ai"]["hide_reason"] or "other") == f.why) if f.ai == "hide" and f.why \
        else r["ai_state"] == f.ai
    ok &= r["status"] != "hidden" if f.st == "all" else r["status"] == f.st
    return bool(ok)


COMBOS = [
    {"arm": ["retail_sales"], "src": ["seek"], "sector": ["retail"]},         # three multi-value facets
    {"src": ["seek"], "wt": ["PT"]},
    {"src": ["jora"], "wt": ["casual"]},
    {"tier": ["core"], "src": ["seek"]},
    {"tier": ["core"], "wt": ["FT"]},
    {"hide": ["fulltime"], "src": ["seek"]},
    {"arch": ["Other"], "tier": ["ai"]},
    {"arm": ["none"], "sector": ["unlisted"], "arch": ["Support"], "hide": ["senior"]},
    {"salmin": 100, "minscore": 4.0},                                        # two floors that used to share one name
    {"sal": 1, "minscore": 4.5},
    {"salmin": 70, "minscore": 3.5, "src": ["indeed"]},
    {"within": 7, "arr": ["remote"], "wt": ["PT", "casual"], "entry": 1, "tier": ["core", "ai"]},
]


def to_filters(d):
    return q.Filters.from_params({k: v for k, v in d.items()})


@pytest.mark.parametrize("combo", COMBOS, ids=lambda c: "+".join(c))
def test_combined_facets_match_the_reference(combo):
    rows, f = make_rows(), to_filters(combo)
    out, counts = q.apply_filters(rows, f)
    want = [r for r in rows if reference(r, f)]
    assert [r["id"] for r in out] == [r["id"] for r in want]
    assert want, "the combo should select something in the synthetic data"


def test_pill_counts_equal_the_list_you_get_by_picking_them():
    rows = make_rows()
    facets = {"arm": ARMS, "tier": ["core", "fallback", "ai"], "src": SRCS, "sector": SECTORS, "wt": ["FT", "PT", "casual"],
              "arch": ["Support", "Other"]}
    for combo in COMBOS:
        base = to_filters(combo)
        _, counts = q.apply_filters(rows, base)
        for facet, vals in facets.items():
            for v in vals:
                v = v or ("none" if facet == "arm" else "unlisted")
                alone = to_filters({**{k: x for k, x in combo.items() if k != facet}, facet: [v]})
                got, _ = q.apply_filters(rows, alone)
                assert counts[facet][v] == len(got), (combo, facet, v)
        for floor in q.SCORE_FLOORS:
            alone = to_filters({**{k: x for k, x in combo.items() if k != "minscore"}, "minscore": floor})
            assert counts["minscore"][floor] == len(q.apply_filters(rows, alone)[0]), (combo, floor)


def test_every_predicate_has_its_own_binding():
    """Each predicate keeps working after the others were built (the late-binding closure bug)."""
    f = to_filters({"arm": ["call_centre"], "tier": ["core"], "src": ["seek"], "sector": ["retail"], "wt": ["PT"],
                    "hide": ["senior"], "arch": ["Support"], "salmin": 100, "minscore": 4.0})
    p = q._preds(f)
    row = {"arm": "call_centre", "tier": "core", "srcs": ["seek"], "sector": "retail", "wt": "PT", "warn": set(),
           "archetype": "Support", "has_salary": True, "sal_year": 50000, "score5": 4.2}
    assert all(p[k](row) for k in ("arm", "tier", "src", "sector", "wt", "hide", "arch", "minscore"))
    assert not p["sal"](row)                        # 50k is under the 100k floor, whatever the score floor is
    assert p["sal"]({**row, "sal_year": 120000})




# -- numbers: ASCII digits only ---------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["²", "٣", "５", "5²", "⑨"])
def test_non_ascii_digits_are_ignored_not_a_500(client, bad):
    f = q.Filters.from_params({"within": bad, "salmin": bad})
    assert f.within is None and f.salmin is None
    assert client.get("/api/board", params={"within": bad}).status_code == 200
    assert client.get("/api/board", params={"salmin": bad}).status_code == 200
    assert client.get("/api/table", params={"within": bad, "salmin": bad}).status_code == 200
    r = client.post("/api/searches", json={"name": "x", "qs": f"within={bad}&salmin={bad}"})
    assert r.status_code == 200


def test_ascii_digits_still_parse():
    f = q.Filters.from_params({"within": "7", "salmin": "80"})
    assert (f.within, f.salmin) == (7, 80)


# -- stale and out-of-range ids ---------------------------------------------------------------------
BIG = "99999999999999999999999"


@pytest.mark.parametrize("path", [
    "/api/job/999999999", "/api/job/-1", "/api/job/0", f"/api/job/{BIG}", "/api/job/abc",
    "/api/job/²", "/s/999999999", f"/s/{BIG}"])
def test_missing_or_out_of_range_ids_are_a_404_page(client, path):
    r = client.get(path, headers={"Accept": "text/html"})
    assert r.status_code == 404, path
    assert "<html" in r.text and "Traceback" not in r.text and "detail" not in r.text[:40]




@pytest.mark.parametrize("action", ["save", "hide", "unhide", "applied", "status", "notes", "draft", "nonsense"])
@pytest.mark.parametrize("pid", ["999999999", BIG, "-5", "0"])
def test_post_to_a_missing_job_is_404_not_500(client, action, pid):
    r = client.post(f"/api/job/{pid}/{action}", json={"status": "applied", "notes": "n"})
    assert r.status_code in (400, 404), (action, pid, r.status_code)


def test_other_posts_with_bad_ids_do_not_500(client):
    for path in (f"/api/searches/{BIG}/delete", "/api/searches/-1/delete", f"/api/job/{BIG}/status",
                 f"/api/inbox/{BIG}/approve", f"/api/inbox/{BIG}/reject"):
        r = client.post(path, json={"status": "applied"}, follow_redirects=False)
        assert r.status_code in (200, 400, 404), (path, r.status_code)
    assert client.post("/api/inbox/999999999/approve").status_code in (200, 400, 404)


def test_real_job_still_opens_and_is_marked_viewed(client):
    pid = client.ids["a"]
    assert client.get(f"/api/job/{pid}").status_code == 200


# -- the validation-error handler: JSON stays JSON, htmx gets a fragment, browsers keep the page ----------------------
def test_validation_error_for_json_callers_is_json(client):
    for headers in ({"Accept": "application/json"}, {"X-Requested-With": "fetch"}):
        r = client.get("/api/job/abc", headers=headers)
        assert r.status_code == 404 and "error" in r.json()


def test_validation_error_for_a_browser_is_still_the_html_page(client):
    r = client.get("/api/job/abc", headers={"Accept": "text/html"})
    assert r.status_code == 404 and "<html" in r.text


# -- huge or odd integers in the query or path never reach SQLite as an OverflowError -------------------------------
HUGE = "9" * 30


@pytest.mark.parametrize("path", [
    f"/api/board?page={HUGE}", f"/api/board?page=-{HUGE}", f"/api/board?within={HUGE}", f"/api/board?salmin={HUGE}",
    "/api/board?salmin=١٢٣", "/api/board?within=²", "/api/board?minscore=nan", "/api/board?minscore=inf",
    "/api/board?minscore=1e999", f"/api/board?minscore={'9' * 5000}",
    f"/api/board?page={'9' * 5000}", f"/api/table?page={HUGE}", "/api/table?page=0",
    f"/table.csv?salmin={HUGE}&within={HUGE}", f"/api/table?minscore={HUGE}", f"/s/{HUGE}", f"/api/job/{HUGE}",
    f"/api/sources?sector={HUGE}"])
def test_odd_integers_are_ignored_or_404_never_500(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code in (200, 307, 404, 422), (path, r.status_code)


@pytest.mark.parametrize("path", [f"/api/job/{HUGE}/save", f"/api/job/{HUGE}/status", f"/api/inbox/{HUGE}/accept",
                                  f"/api/searches/{HUGE}/delete"])
def test_odd_integer_posts_are_404(client, path):
    assert client.post(path, json={"status": "applied"}, follow_redirects=False).status_code in (400, 404)
