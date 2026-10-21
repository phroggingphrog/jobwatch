"""Synthetic whole-ad and evidence-isolation acceptance through actual role tools."""
from __future__ import annotations

import copy
import json

import pytest

from jobwatch.candidate.contracts import content_hash
from jobwatch.candidate.evidence import bind_career_profile, snapshot_evidence
from pipeline.agentic.contracts import AgenticError, Requirement, RequirementSet, RunKey, SourceCitation
from pipeline.agentic.evaluator import evaluate_job
from pipeline.agentic.runtime import BatchBudget, JobBudget


class FakeModel:
    def __init__(self, choices):
        self.choices = iter(choices)
        self.seen = []

    def chat_once(self, model, messages, **kwargs):
        self.seen.append(copy.deepcopy(messages))
        return next(self.choices)


def build_case(tmp_path, *, skill="Reconciled ledgers", ad_skill="Reconciled ledgers", score=4.2,
               match="strong", tail="", career_profile="Target accounting; do not target hospitality."):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "cv.md").write_text(f"# Synthetic candidate\n\n## Skills\n- {skill}\n")
    bundle = bind_career_profile(snapshot_evidence(tmp_path), career_profile)
    ad = f"Junior accounting analyst based in Melbourne. Part-time, 24 hours per week. Requires {ad_skill}." + tail
    h = content_hash(ad.encode())
    key = RunKey(posting_id=1, ad_hash=h, evidence_hash=bundle.bundle_hash,
                 rubric_version="test", config_hash="2" * 64)
    requirements = RequirementSet(ad_hash=h, requirements=(Requirement(
        id="r1", text=ad_skill, tier="stated", importance="high",
        jd_signal=SourceCitation(source_id="ad", content_hash=h, quote=ad_skill)),))
    facts = {"real_job": True, "role_family": "accounting", "duties": ["reconcile ledgers"],
             "required_skills": [ad_skill], "preferred_skills": [], "seniority": "junior",
             "min_years": None, "hours": "part_time_ok", "program": False,
             "work_rights": {"requirement": "none_stated", "quote": ""}, "screening_questions": []}
    extraction = {"requirements": requirements.model_dump(mode="json"), "facts": facts,
                  "location_fit": "melbourne", "location_evidence": {
                      "source_id": "ad", "content_hash": h, "quote": "based in Melbourne"},
                  "legitimacy": "verified", "uncertainties": []}
    item = bundle.items[0]
    assessment = {"requirements_hash": requirements.requirement_hash, "matches": [{
        "requirement_id": "r1", "match": match,
        "evidence": [{"source_id": item.source_file, "content_hash": item.source_hash,
                      "quote": item.quote}] if match in {"strong", "partial"} else [],
        "risk": "Required experience not demonstrated" if match != "strong" else "",
        "mitigation": "Obtain supervised practice and document the result" if match != "strong" else "",
    }], "archetype": "entry accounting", "global_score": score,
        "dimensions": {name: {"score": score, "reason": "Bound synthetic evidence reviewed"}
                       for name in ("cv_match", "north_star", "compensation", "culture", "red_flags")},
        "report": {k: "Evidence-grounded synthetic analysis" for k in "ABCDEFG"}}
    choices = [
        {"tool": "read_full_ad", "arguments": {}},
        {"tool": "complete_requirements", "arguments": extraction},
        {"tool": "read_candidate_evidence", "arguments": {"evidence_ids": [item.id]}},
        {"tool": "complete_job_assessment", "arguments": assessment},
    ]
    return bundle, ad, key, choices


def budget(key):
    return JobBudget(key.value, BatchBudget("synthetic", token_ceiling=2_000_000), token_ceiling=1_000_000)


def test_layout_only_quote_change_restores_exact_source_before_freezing(tmp_path):
    bundle, ad, key, choices = build_case(tmp_path, ad_skill="Reconciled\nledgers")
    choices[1]['arguments']['requirements']['requirements'][0]['jd_signal']['quote'] = 'Reconciled ledgers'
    result = evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)
    citation = result.requirements.requirements[0].jd_signal
    assert citation.quote == 'Reconciled\nledgers' and citation.quote in ad
    assert result.requirements.requirement_hash == choices[-1]['arguments']['requirements_hash']


@pytest.mark.parametrize('quote,source,wrong_hash,ad', [
    ('Reconciled accounts', 'ad', False, 'Reconciled\nledgers'),
    ('reconciled ledgers', 'ad', False, 'Reconciled\nledgers'),
    ('Reconciled ledgers', 'cv.md', False, 'Reconciled\nledgers'),
    ('Reconciled ledgers', 'ad', True, 'Reconciled\nledgers'),
    ('Reconciled ledgers', 'ad', False, 'Reconciled\nledgers; Reconciled\tledgers'),
    ('Reconciled ledgers', 'ad', False, 'Reconciled, ledgers'),
])
def test_layout_conversion_never_repairs_wording_identity_or_ambiguous_quotes(quote,source,wrong_hash,ad):
    from pipeline.agentic.evaluator import _exact_ad_citation
    h=content_hash(ad.encode())
    citation=SourceCitation(source_id=source,content_hash='0'*64 if wrong_hash else h,quote=quote)
    with pytest.raises(AgenticError,match='invalid_citation'):
        _exact_ad_citation(citation,ad,h)


def test_two_actual_agent_passes_keep_candidate_out_of_full_jd_context(tmp_path):
    tail = " Evidence-end-marker-782. " + "Details. " * 1700 + "Final material requirement."
    bundle, ad, key, choices = build_case(tmp_path, tail=tail)
    model = FakeModel(choices)
    result = evaluate_job(key, ad, budget(key), model, evidence_bundle=bundle)
    assert result.global_score == 4.2
    assert result.requirements.requirement_hash == choices[-1]["arguments"]["requirements_hash"]
    assert result.matches[0].evidence[0].source_id == "cv.md"
    assert len(model.seen) == 4
    first_context = json.loads(model.seen[0][-1]["content"])
    assert first_context == {"ad_hash": key.ad_hash, "ad_text": ad}
    assert "Final material requirement." in first_context["ad_text"]
    assert bundle.bundle_hash not in json.dumps(model.seen[:2])
    assert "Target accounting; do not target hospitality." not in json.dumps(model.seen[:2])
    assert "Target accounting; do not target hospitality." in json.dumps(model.seen[2:])


@pytest.mark.parametrize("skill,ad_skill,score,match", [
    ("Reconciled ledgers", "Reconciled ledgers", 4.2, "strong"),
    ("Built SQL dashboards", "Cashflow modelling", 2.3, "missing"),
    ("Prepared cashflow models", "Cashflow modelling", 3.5, "partial"),
])
def test_distinct_ads_and_candidates_produce_real_variable_results(tmp_path, skill, ad_skill, score, match):
    bundle, ad, key, choices = build_case(tmp_path, skill=skill, ad_skill=ad_skill, score=score, match=match)
    result = evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)
    assert result.global_score == score
    assert result.matches[0].match == match
    assert result.requirements.requirements[0].text == ad_skill


def test_paid_model_accounting_analysis_label_uses_canonical_family_before_gate(tmp_path):
    from jobwatch.candidate.policy import default_policy
    from pipeline.agentic.gate import decide
    bundle, ad, key, choices = build_case(tmp_path, score=4.0)
    choices[1]["arguments"]["facts"]["role_family"] = "Accounting analysis"
    model = FakeModel(choices)
    result = evaluate_job(key, ad, budget(key), model, evidence_bundle=bundle)
    assert result.facts.role_family == "accounting"
    assert decide(result, ad_text=ad, title="Junior accounting analyst", policy=default_policy(),
                  captured_complete=True, expected_run_key=key, evidence_bundle=bundle).route == "draft"
    prompt = model.seen[0][0]["content"]
    assert "customer_service" in prompt and "finance_clerical" in prompt and "unknown" in prompt


@pytest.mark.parametrize("family", ["Novel unclassified role", "Customer service accounting analysis"])
def test_unknown_family_is_not_silently_promoted_to_an_owner_target(tmp_path, family):
    bundle, ad, key, choices = build_case(tmp_path)
    choices[1]["arguments"]["facts"]["role_family"] = family
    choices.insert(2, copy.deepcopy(choices[1]))  # Correction still supplies an unsupported family.
    with pytest.raises(AgenticError, match="invalid_tool_arguments"):
        evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)


@pytest.mark.parametrize("family", ["customer_service", "hospitality", "retail", "shop_floor", "other"])
def test_neutral_jd_family_vocabulary_preserves_non_target_roles(tmp_path, family):
    from jobwatch.candidate.policy import default_policy
    from pipeline.agentic.gate import decide
    bundle, ad, key, choices = build_case(tmp_path)
    choices[1]["arguments"]["facts"]["role_family"] = family
    result = evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)
    assert result.facts.role_family == family
    assert decide(result, ad_text=ad, title="Junior analyst", policy=default_policy(),
                  captured_complete=True, expected_run_key=key, evidence_bundle=bundle).route == "archive"


@pytest.mark.parametrize("source", ["ad", "career_ops_profile.md", "research"])
def test_job_ad_preferences_and_research_cannot_prove_candidate_qualifications(tmp_path, source):
    bundle, ad, key, choices = build_case(tmp_path)
    citation = choices[-1]["arguments"]["matches"][0]["evidence"][0]
    citation.update(source_id=source, content_hash=key.ad_hash, quote="Reconciled ledgers")
    with pytest.raises(AgenticError, match="invalid_citation"):
        evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)


@pytest.mark.parametrize("change,error", [
    ("requirements_hash", "requirements_changed"),
    ("citation_hash", "invalid_citation"),
    ("citation_quote", "invalid_citation"),
    ("missing_coverage", "invalid_evaluation"),
    ("not_applicable", "invalid_tool_arguments"),
])
def test_frozen_requirements_full_coverage_and_citations_fail_closed(tmp_path, change, error):
    bundle, ad, key, choices = build_case(tmp_path)
    output = choices[-1]["arguments"]
    if change == "requirements_hash": output["requirements_hash"] = "a" * 64
    elif change == "citation_hash": output["matches"][0]["evidence"][0]["content_hash"] = "a" * 64
    elif change == "citation_quote": output["matches"][0]["evidence"][0]["quote"] = "Invented qualification"
    elif change == "missing_coverage": output["matches"] = []
    elif change == "not_applicable":
        output["matches"][0].update(match="not_applicable", evidence=[])
        choices.append(copy.deepcopy(choices[-1]))
    with pytest.raises(AgenticError, match=error):
        evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)


def test_hash_or_profile_change_is_rejected_before_model_call(tmp_path):
    bundle, ad, key, choices = build_case(tmp_path)
    for changed_key, changed_ad, profile in [
        (key, ad + "changed", ""), (key.model_copy(update={"evidence_hash": "a" * 64}), ad, ""),
        (key, ad, "Different career priorities"),
    ]:
        model = FakeModel(choices)
        with pytest.raises(AgenticError):
            evaluate_job(changed_key, changed_ad, budget(changed_key), model,
                         evidence_bundle=bundle, career_profile=profile)
        assert model.seen == []


def test_public_research_tool_choice_has_no_candidate_query_surface(tmp_path):
    from pipeline.agentic.research import ResearchCapability, PublicSnapshot
    bundle, ad, key, choices = build_case(tmp_path)
    calls = []
    class Search:
        def search(self, query, **kwargs):
            calls.append(query)
            return [{"result_id": "public-1", "title": "Public employer", "url": "https://example.com/about"}]
    b = budget(key)
    research = ResearchCapability(PublicSnapshot("Example Employer", "Junior Analyst", "https://example.com/job"),
                                  budget=b, search_provider=Search())
    choices.insert(-1, {"tool": "research_employer", "arguments": {"intent": "employer_identity"}})
    result = evaluate_job(key, ad, b, FakeModel(choices), evidence_bundle=bundle, research=research)
    assert result.research_available
    assert calls == ["Example Employer official website"]
    assert b.snapshot().research_queries == 1


def test_public_research_unavailable_is_honest_and_does_not_abort_evidence_assessment(tmp_path):
    from pipeline.agentic.research import ResearchCapability, PublicSnapshot
    bundle, ad, key, choices = build_case(tmp_path)
    b = budget(key)
    research = ResearchCapability(PublicSnapshot("Example Employer", "Junior Analyst", "https://example.com/job"), budget=b)
    choices.insert(-1, {"tool": "research_employer", "arguments": {"intent": "compensation"}})
    result = evaluate_job(key, ad, b, FakeModel(choices), evidence_bundle=bundle, research=research)
    assert not result.research_available


def test_all_extracted_requirements_are_covered_with_frozen_importance(tmp_path):
    bundle, ad, key, choices = build_case(tmp_path, tail=" Preferred SQL reporting.")
    second = {"id": "r2", "text": "SQL reporting", "tier": "stated", "importance": "preferred",
              "jd_signal": {"source_id": "ad", "content_hash": key.ad_hash, "quote": "Preferred SQL reporting."}}
    req_payload = choices[1]["arguments"]["requirements"]
    req_payload["requirements"].append(second)
    from pipeline.agentic.runtime import validate_model_payload
    expected = validate_model_payload(RequirementSet, req_payload)
    choices[-1]["arguments"]["requirements_hash"] = expected.requirement_hash
    choices[-1]["arguments"]["matches"].append({"requirement_id": "r2", "match": "missing", "evidence": []})
    result = evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)
    assert result.requirements == expected
    assert result.requirements.requirements[1].importance == "preferred"
    assert {match.requirement_id for match in result.matches} == {"r1", "r2"}


def test_uncertain_jd_facts_remain_visible_in_report(tmp_path):
    bundle, ad, key, choices = build_case(tmp_path)
    choices[1]["arguments"]["uncertainties"] = ["Exact working days not stated"]
    result = evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)
    assert "Exact working days not stated" in result.report["E"]


def test_job_requirement_cannot_cite_candidate_source(tmp_path):
    bundle, ad, key, choices = build_case(tmp_path)
    choices[1]["arguments"]["requirements"]["requirements"][0]["jd_signal"] = {
        "source_id": "cv.md", "content_hash": bundle.sources["cv.md"], "quote": "Reconciled ledgers"}
    with pytest.raises(AgenticError, match="invalid_citation"):
        evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)


def test_descriptive_report_headings_preserve_complete_validated_report(tmp_path):
    bundle, ad, key, choices = build_case(tmp_path)
    report = choices[-1]['arguments']['report']
    choices[-1]['arguments']['report'] = {f'{k}_section_title': v for k, v in report.items()}
    result = evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)
    assert result.report == report


@pytest.mark.parametrize('keys', [list('ABCDEF'), list('ABCDEFG') + ['A_duplicate'], list('ABCDEF') + ['H_unknown']])
def test_report_heading_normalization_never_drops_or_fabricates_sections(tmp_path, keys):
    bundle, ad, key, choices = build_case(tmp_path)
    choices[-1]['arguments']['report'] = {k: 'Unchanged text' for k in keys}
    with pytest.raises(AgenticError):
        evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)


def test_contradictory_match_gets_one_bounded_schema_correction(tmp_path):
    bundle, ad, key, choices = build_case(tmp_path,match='missing')
    bad=copy.deepcopy(choices[-1])
    item=bundle.items[0]
    bad['arguments']['matches'][0]['evidence']=[{'source_id':item.source_file,
        'content_hash':item.source_hash,'quote':item.quote}]
    model=FakeModel(choices[:-1]+[bad,choices[-1]])
    result=evaluate_job(key,ad,budget(key),model,evidence_bundle=bundle)
    assert result.matches[0].match=='missing' and not result.matches[0].evidence
    assert len(model.seen)==5


def test_repeated_contradictory_match_cannot_expand_correction_budget(tmp_path):
    bundle, ad, key, choices = build_case(tmp_path)
    choices[-1]['arguments']['matches'][0]['match']='missing'
    model=FakeModel(choices+[copy.deepcopy(choices[-1])])
    with pytest.raises(AgenticError,match='invalid_tool_arguments'):
        evaluate_job(key,ad,budget(key),model,evidence_bundle=bundle)
    assert len(model.seen)==5


def test_essential_not_applicable_gets_existing_bounded_correction(tmp_path):
    bundle, ad, key, choices=build_case(tmp_path)
    bad=copy.deepcopy(choices[-1]);bad['arguments']['matches'][0].update(match='not_applicable',evidence=[])
    model=FakeModel(choices[:-1]+[bad,choices[-1]])
    result=evaluate_job(key,ad,budget(key),model,evidence_bundle=bundle)
    assert result.matches[0].match=='strong'
    assert len(model.seen)==5


def test_repeated_essential_not_applicable_stops_after_one_correction(tmp_path):
    bundle, ad, key, choices=build_case(tmp_path)
    choices[-1]['arguments']['matches'][0].update(match='not_applicable',evidence=[])
    model=FakeModel(choices+[copy.deepcopy(choices[-1])])
    with pytest.raises(AgenticError,match='invalid_tool_arguments'):
        evaluate_job(key,ad,budget(key),model,evidence_bundle=bundle)
    assert len(model.seen)==5


def test_jd_research_precedes_frozen_facts_without_candidate_data(tmp_path):
    from pipeline.agentic.research import ResearchCapability, PublicSnapshot
    bundle, ad, key, choices = build_case(tmp_path, career_profile='PRIVATE-PROFILE-MARKER')
    queries, fetched = [], []
    class Search:
        def search(self, query, **kwargs):
            queries.append(query)
            return [{'result_id': 'public-1', 'title': 'Employer', 'url': 'https://example.com/about'}]
    class Fetcher:
        def fetch(self, url, **kwargs):
            fetched.append(url)
            return 'Public employer vacancy identity'
    b = budget(key)
    research = ResearchCapability(PublicSnapshot('Example Employer', 'Junior Analyst', 'https://example.com/job'),
                                  budget=b, search_provider=Search(), fetcher=Fetcher())
    choices[1:1] = [
        {'tool': 'research_employer', 'arguments': {'intent': 'employer_identity'}},
        {'tool': 'read_public_page', 'arguments': {'result_id': 'unknown-result'}},
        {'tool': 'read_public_page', 'arguments': {'result_id': 'public-1'}},
    ]
    model = FakeModel(choices)
    result = evaluate_job(key, ad, b, model, evidence_bundle=bundle, research=research)
    assert result.research_available
    assert queries == ['Example Employer official website']
    assert fetched == ['https://example.com/about']
    assert b.snapshot().research_queries == 1
    assert b.snapshot().research_pages == 1
    first_phase = json.dumps(model.seen[:5])
    assert 'Public employer vacancy identity' in first_phase
    assert 'unavailable' in first_phase
    assert 'PRIVATE-PROFILE-MARKER' not in first_phase
    assert bundle.bundle_hash not in first_phase
    assert 'cv.md' not in first_phase
    assert json.loads(model.seen[0][-1]['content'])['public_job']['employer'] == 'Example Employer'


def test_jd_research_unavailable_does_not_abort(tmp_path):
    from pipeline.agentic.research import ResearchCapability, PublicSnapshot
    bundle, ad, key, choices = build_case(tmp_path)
    b = budget(key)
    research = ResearchCapability(PublicSnapshot('Employer', 'Analyst', 'https://example.com/job'), budget=b)
    choices.insert(1, {'tool': 'research_employer', 'arguments': {'intent': 'employer_identity'}})
    model = FakeModel(choices)
    result = evaluate_job(key, ad, b, model, evidence_bundle=bundle, research=research)
    assert not result.research_available
    assert 'unavailable' in json.dumps(model.seen[2])


def test_research_budget_mismatch_rejected_before_jd_call(tmp_path):
    from pipeline.agentic.research import ResearchCapability, PublicSnapshot
    bundle, ad, key, choices = build_case(tmp_path)
    research = ResearchCapability(PublicSnapshot('Employer', 'Analyst', 'https://example.com/job'), budget=budget(key))
    model = FakeModel(choices)
    with pytest.raises(AgenticError, match='invalid_research_capability'):
        evaluate_job(key, ad, budget(key), model, evidence_bundle=bundle, research=research)
    assert model.seen == []


def test_unknown_family_follows_the_archetype_opus_named(tmp_path):
    """2026-10-12: 'unknown' is read from the archetype (KPMG Vacationer); a non-target archetype still archives."""
    from jobwatch.candidate.policy import default_policy
    from pipeline.agentic.gate import decide
    for archetype, route in (("Tax / Graduate Accountant", "draft"), ("Retail sales", "archive")):
        bundle, ad, key, choices = build_case(tmp_path / archetype[:4])
        choices[1]["arguments"]["facts"]["role_family"] = "unknown"
        for c in choices[2:]:
            if "archetype" in c.get("arguments", {}):
                c["arguments"]["archetype"] = archetype
        result = evaluate_job(key, ad, budget(key), FakeModel(choices), evidence_bundle=bundle)
        assert decide(result, ad_text=ad, title="Junior analyst", policy=default_policy(), captured_complete=True,
                      expected_run_key=key, evidence_bundle=bundle).route == route
