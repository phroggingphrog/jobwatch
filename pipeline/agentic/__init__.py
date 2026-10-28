"""Stable public exports for agentic wire contracts. No import-time side effects."""
from .contracts import (
    AgenticError, AgenticEvaluation, AgenticGateDecision, AgenticScreeningAnswer, BudgetCheckpoint,
    Dimension, DraftProposal, PackageManifest, PublicAgenticError, Requirement, RequirementMatch, RequirementSet, Reservation,
    ReviewVerdict, RunKey, SourceCitation, check_frozen_requirements,
    validate_citations, validate_review, parse_budget_checkpoint_json, answers_content_hash,
)
from .gate import decide
from .runtime import (
    BatchBudget, JobBudget, RoleResult, RoleSpec, RuntimeErrorSafe, Tool, run_role,
)
from .research import (
    PublicSnapshot, ResearchCapability, ResearchIntent, ResearchPage, ResearchResult, ResearchUnavailable, SafeFetcher,
)
from .store import AgenticStore, Claim
_LAZY = {
    "PersistenceAdapter": "persistence", "evaluate_job": "evaluator",
    "draft_and_review": "draft", "build_form_map": "forms", "review_proposal": "review",
    "run_agentic_job": "service", "agentic_batch_run": "service",
}


def __getattr__(name):
    """Load high-level orchestration only when used, avoiding candidate import cycles."""
    if name not in _LAZY:
        raise AttributeError(name)
    from importlib import import_module
    value = getattr(import_module(f".{_LAZY[name]}", __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "AgenticError", "AgenticEvaluation", "AgenticGateDecision", "AgenticScreeningAnswer", "BudgetCheckpoint",
    "Dimension", "DraftProposal", "PackageManifest", "PublicAgenticError", "Requirement", "RequirementMatch",
    "RequirementSet", "Reservation", "ReviewVerdict", "RunKey", "SourceCitation", "check_frozen_requirements",
    "validate_citations", "validate_review", "parse_budget_checkpoint_json", "answers_content_hash",
    "decide",
    "BatchBudget", "JobBudget", "RoleResult", "RoleSpec", "RuntimeErrorSafe", "Tool", "run_role",
    "PublicSnapshot", "ResearchCapability", "ResearchIntent", "ResearchPage", "ResearchResult", "ResearchUnavailable", "SafeFetcher",
    "AgenticStore", "Claim", "PersistenceAdapter", "evaluate_job",
    "draft_and_review", "build_form_map", "review_proposal",
    "run_agentic_job", "agentic_batch_run",
]
