from types import SimpleNamespace

from jobwatch.occupations.plan import SearchPlan, search_plan, title_shaped


def policy(focus):
    return SimpleNamespace(focus=focus, profile_version=1, policy_hash='p', home={}, regions=())


def test_sentence_focus_is_dropped_and_title_kept():
    plan = search_plan(policy(["Looking for a supervised entry role, about three days a week.", "graduate analyst"]), [])
    assert plan.queries['seek'] == ('graduate analyst',)
    assert plan.dropped_focus == 1
    assert SearchPlan.model_validate(plan.model_dump(mode='json')) == plan      # hash still verifies with the count


def test_all_titles_keep_the_old_hash_shape():
    plan = search_plan(policy(["graduate analyst", "data/finance intern"]), [])
    assert plan.dropped_focus == 0 and len(plan.queries['jora']) == 2
    assert not title_shaped("one two three four five six seven") and not title_shaped("role.")
