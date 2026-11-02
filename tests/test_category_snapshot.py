import pytest
from pydantic import ValidationError

from pipeline.category_snapshot import CategorySnapshot


def category(id="a", priority=0, **changes):
    return {"id": id, "label": id, "priority": priority, "phrases": [" Example "],
            "action": "admit", "promote": True, "hours": "standard", **changes}


def test_empty_and_opaque_ordered_categories():
    assert CategorySnapshot().ordered() == ()
    snapshot = CategorySnapshot.model_validate({"categories": [category("z", 3), category("x", 1)]})
    assert [item.id for item in snapshot.ordered()] == ["x", "z"]
    assert snapshot.get("z").phrases == ("example",)
    assert snapshot.get("missing") is None


@pytest.mark.parametrize("categories", [
    [category("unsure")], [category("bad id")], [category("a"), category("a", 1)],
    [category("a"), category("b")], [category(action="discard")],
    [category(promote="yes")], [category(phrases=[" "])], [category(priority=-1)],
])
def test_invalid_configuration_is_rejected(categories):
    with pytest.raises(ValidationError):
        CategorySnapshot.model_validate({"categories": categories})
