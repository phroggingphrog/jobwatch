import re

import pytest

from jobwatch.apply.careerops_cv import ats_check, cv_html, fill_entry, parse_partial, render_cv_pdf


class _Profile:
    name = "Synthetic Candidate"
    header_lines = ["# Synthetic Candidate", "Melbourne, VIC | 0400 000 000 | synthetic@example.com | linkedin.com/in/synthetic"]
    by_id = {"pf.experience.0.title": {"text": "Graduate Accountant"}, "pf.experience.0.company": {"text": "Example Tax"},
             "pf.experience.0.period": {"text": "29 May 2025 – 4 November 2025"},
             "pf.experience.1.title": {"text": "Accountant"}, "pf.experience.1.company": {"text": "Example Tax"},
             "pf.experience.1.period": {"text": "20 June 2026 – 4 August 2026"},
             "pf.education.0.degree": {"text": "Master of Analytics"}, "pf.education.0.institution": {"text": "RMIT"}}


def _claim(text):
    return {"id": "c", "text": text, "evidence_ids": ["x"], "tier": "stated"}


CONTENT = {"cv": {"summary": [_claim("Accounting graduate reviewing individual tax returns.")],
                  "skills": [_claim("Reconciliations"), _claim("Microsoft Excel")],
                  "experience": [{"role_ids": ["pf.experience.1.title"], "overview": [_claim("Tax season role.")],
                                  "bullets": [_claim("Reviewed returns before lodgement")], "achievements": []},
                                 {"role_ids": ["pf.experience.0.title"], "bullets": [_claim("Liaised with the ATO")],
                                  "achievements": [_claim("Supported clients through ATO audits")]}],
                  "education": [{"entry_ids": ["pf.education.0.degree"], "bullets": []}],
                  "certifications": [], "additional": [_claim("Student visa (subclass 500)")]}}


def test_partial_fill_matches_career_ops_semantics():
    entry, blocks = parse_partial("doc<!--ENTRY--><p>{{A}}{{B_BLOCK}}</p><!--B_BLOCK--><i>{{B}}</i><!--/B_BLOCK-->"
                                  "<!--B_EMPTY--><i>-</i><!--/B_EMPTY--><!--/ENTRY-->")
    assert fill_entry(entry, blocks, {"A": "x"}, {"B_BLOCK": ("y", True)}) == "<p>x<i>y</i></p>"
    assert fill_entry(entry, blocks, {"A": "$&"}, {"B_BLOCK": ("", False)}) == "<p>$&<i>-</i></p>"


def test_cv_html_merges_one_employer_and_prints_work_rights_once():
    page = cv_html(CONTENT, _Profile(), "cv_graduate_2page")
    assert page.count('class="job"') == 1 and "Accountant / Graduate Accountant" in page
    assert "June 2026 – August 2026 | May 2025 – November 2025" in page
    assert "Key Achievements" in page and "Role Overview" in page
    assert len(re.findall(r"subclass 500", page)) == 1 and "{{" not in page
    assert "PROJECTS" not in page.upper().split("<BODY", 1)[1] or "Projects</div>" not in page


def test_ats_check_flags_columns_and_missing_headings():
    assert ats_check('<meta charset="UTF-8"><div style="column-count:2">', "short")["grade"] == "F"


@pytest.mark.real_cv_printer
def test_real_print_is_ats_grade_a():
    pdf, info = render_cv_pdf(CONTENT, _Profile(), "cv_graduate_2page")
    assert pdf.startswith(b"%PDF") and info["ats"]["grade"] == "A", info


def test_confirmed_templates_change_section_order_consistently_with_markdown():
    graduate = cv_html(CONTENT, _Profile(), 'cv_graduate_2page')
    compact = cv_html(CONTENT, _Profile(), 'cv_compact_1page')
    assert graduate.index('>Education</div>') < graduate.index('>Professional Experience</div>')
    assert compact.index('>Professional Experience</div>') < compact.index('>Education</div>')
    assert compact.index('>Education</div>') < compact.index('>Core Capabilities</div>')
