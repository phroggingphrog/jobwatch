"""CI security posture: pull-request workflows never gain repository write or run untrusted merge refs."""
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _documents() -> dict[str, dict]:
    return {path.name: yaml.safe_load(path.read_text()) for path in sorted(WORKFLOWS.iterdir())}


def _triggers(document: dict) -> dict:
    value = document.get("on", document.get(True))
    return value if isinstance(value, dict) else {value: {}}


def test_no_workflow_uses_pull_request_target():
    for name, document in _documents().items():
        assert "pull_request_target" not in _triggers(document), name


def test_security_workflows_run_on_pull_requests_with_read_only_permissions():
    documents = _documents()
    for name in ("codeql.yml", "dependency-review.yml", "personal-data-guard.yml"):
        document = documents[name]
        assert "pull_request" in _triggers(document), name
        assert set(document["permissions"].values()) <= {"read"}, name


def test_only_codeql_may_write_security_events():
    for name, document in _documents().items():
        for job in (document.get("jobs") or {}).values():
            write = {scope for scope, value in (job.get("permissions") or {}).items() if value == "write"}
            assert not write or (name == "codeql.yml" and write == {"security-events"}), (name, write)
