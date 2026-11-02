import pytest
from pydantic import ValidationError

from pipeline.nodes.ingest import make_ad
from pipeline.schemas import JobAd


@pytest.mark.parametrize("kind", ["full", "partial", "teaser"])
def test_job_ad_accepts_available_text_kinds(kind):
    posting = {"id": 1, "source": "test", "title": "Engineer", "company": "Acme",
               "location": "Melbourne", "url": "https://example.com/job"}
    ad = make_ad(posting, "Short ad", kind, "local")
    assert ad.text_kind == kind
    assert len(ad.content_hash) == 64
    assert JobAd.model_validate(ad.model_dump()) == ad


@pytest.mark.parametrize("field,value", [("text_kind", "unknown"), ("content_hash", "bad"),
                                        ("posting_id", 0), ("title", "")])
def test_job_ad_rejects_invalid_contract_fields(field, value):
    data = {"posting_id": 1, "source": "test", "title": "Engineer", "company": "Acme",
            "location": "Melbourne", "url": "https://example.com/job", "location_rule": "local",
            "text_kind": "full", "content_hash": "a" * 64}
    data[field] = value
    with pytest.raises(ValidationError):
        JobAd.model_validate(data)
