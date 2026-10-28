import jobwatch.apply.jev_forms as jf


def test_jev_sees_labels_only_and_code_types_the_value(monkeypatch, tmp_path):
    (tmp_path / "profile.yaml").write_text("candidate:\n  name: Ann Example Lee\n  email: ann@example.com\n")
    (tmp_path / "answers.yaml").write_text('work_rights:\n  visa_type: "Student (subclass 500)"\nsalary:\n  expected_annual_aud: ""\n')
    sent = []

    def fake_post(cfg, path, body):
        sent.append(str(body))
        return {"answers": {"f0": {"choice": "contact.email", "confidence": 0.97},
                            "f1": {"choice": "work_rights.visa_type", "confidence": 0.95},
                            "f2": {"choice": "contact.last_name", "confidence": 0.4}}}

    monkeypatch.setattr(jf, "_post", fake_post)
    fields = [{"key": "a", "question": "Email", "type": "email"},
              {"key": "b", "question": "Visa", "type": "select",
               "options": [{"value": "v1", "label": "Citizen"}, {"value": "v2", "label": "Student (subclass 500)"}]},
              {"key": "c", "question": "Surname", "type": "text"}]
    records = jf.jev_prefill(fields, tmp_path)
    assert records["a"]["value"] == "ann@example.com" and records["a"]["owner_verified"] is True
    assert records["b"]["value"] == "v2"          # option chosen by code from the owner's value
    assert "c" not in records                      # low confidence -> answer agent
    assert not any(v in s for s in sent for v in ("ann@example.com", "Ann Example Lee"))  # owner values never go to Jev


def test_next_button_never_offers_submit_like_labels(monkeypatch):
    offered = []

    def fake_post(cfg, path, body):
        offered.append(body["questions"]["next"]["criteria"])
        return {"answers": {"next": {"choice": "b0", "confidence": 0.9}}}

    monkeypatch.setattr(jf, "_post", fake_post)
    chosen = jf.jev_next_button([{"label": "Proceed to step 2", "non_submit": True},
                                 {"label": "Submit Application", "non_submit": True}])
    assert chosen["label"] == "Proceed to step 2"
    assert "Submit Application" not in offered[0].values()


def test_first_name_is_everything_before_the_surname(tmp_path):
    (tmp_path / "profile.yaml").write_text("candidate:\n  name: Ann Marie Lee\n")
    catalog = jf.answer_catalog(tmp_path)
    assert catalog["contact.first_name"][1] == "Ann Marie" and catalog["contact.last_name"][1] == "Lee"


def test_career_facts_follow_the_generator_contract(tmp_path):
    from jobwatch.apply.career_retrieval import career_facts
    (tmp_path / "career_master.yaml").write_text("""
candidate: {name: Ann Lee, date_of_birth: '2000-01-01', languages: [English], referees: [{name: Bob}]}
bullet_bank:
  - {id: b1, text_canonical: Reconciled ledgers, include_in_master: true}
  - {id: b2, text_canonical: Overstated claim, include_in_master: false}
cover_letter_blocks:
  - {id: c1, text: My own words, use: active}
  - {id: c2, text: Old words, use: retired}
skill_bank:
  - {id: s1, name: MYOB, safe_to_claim: true}
  - {id: s2, name: SAP, safe_to_claim: false}
""")
    text = "\n".join(career_facts(tmp_path).values())
    assert "Reconciled ledgers" in text and "My own words" in text and "MYOB" in text
    for banned in ("Overstated claim", "Old words", "SAP", "2000-01-01", "Bob"):
        assert banned not in text
