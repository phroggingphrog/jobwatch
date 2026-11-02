from pipeline.decision import build_decision


def test_low_fit_and_model_recommendation_do_not_authorize_exclusion():
    result=build_decision(fit_score=1.0,recommendation='exclude')
    assert result.recommendation=='consider'
    assert result.explicit_conflicts==()


def test_unknowns_preserve_assessment_and_do_not_become_errors():
    result=build_decision(fit_score=4.5,unknowns=['quote not verified','hours unknown'])
    assert result.completeness=='partial'
    assert result.recommendation=='needs_clarification'
    assert result.errors==()
    assert result.fit_score==4.5


def test_explicit_conflict_separate_from_high_fit():
    result=build_decision(fit_score=5,explicit_conflicts=['citizenship requirement'])
    assert result.recommendation=='exclude'
    assert result.fit_score==5


def test_errors_are_not_missing_evidence():
    result=build_decision(errors=['gateway timeout'])
    assert result.recommendation=='retry' and result.completeness=='unavailable'
    partial=build_decision(fit_score=3,errors=['report export failed'])
    assert partial.completeness=='partial' and partial.recommendation=='consider'
