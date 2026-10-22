"""New legacy readings classify neutral families; old stored JobFacts remain readable."""
import json

from jobwatch.candidate.contracts import JOB_ROLE_FAMILIES
from jobwatch.llm import LLM
from pipeline.nodes import extract
from pipeline.schemas import JobFacts
from test_personal_legacy_gate import facts


def test_new_extraction_retries_noncanonical_family_instead_of_guessing_alias():
    outputs = [facts().model_copy(update={'role_family': 'retail sales floor'}).model_dump(),
               facts().model_copy(update={'role_family': 'retail'}).model_dump()]
    requests = []
    def transport(url, headers, body, timeout):
        requests.append(body)
        return 200, {'choices': [{'message': {'content': json.dumps(outputs[min(len(requests) - 1, 1)])}}]}
    result, attempts = extract.run(LLM(transport=transport, keys=['synthetic']), 'openai/sol',
                                   'Shop assistant', 'Example', 'Sydney NSW', 'Serve customers in store.')
    assert result.role_family == 'retail' and attempts == 2
    system = requests[0]['messages'][0]['content']
    assert all(family in system for family in JOB_ROLE_FAMILIES)
    assert '2-6 words' not in system


def test_new_extraction_normalizes_spelling_but_unknown_stays_unknown():
    parsed = extract.ExtractedJobFacts.model_validate(facts().model_copy(update={'role_family': 'Finance clerical'}).model_dump())
    assert parsed.role_family == 'finance_clerical'
    assert extract.ExtractedJobFacts.model_validate(facts().model_copy(update={'role_family': 'unknown'}).model_dump()).role_family == 'unknown'


def test_historical_stored_family_keeps_its_original_representation():
    stored = facts().model_copy(update={'role_family': 'retail sales floor'}).model_dump()
    assert JobFacts.model_validate(stored).role_family == 'retail sales floor'
