import pytest

from investment_evidence_engine.append_replay import resume_prefix_length


def _entry(key, value):
    return {"event_id": key, "scope": "SYNTHETIC", "payload": {"value": value}}


PLAN = [_entry("intent", "whole-plan-digest"), _entry("first", 1), _entry("second", 2)]
OTHER = _entry("unrelated", 0)


@pytest.mark.parametrize(("observed", "count"), [
    ([], 0), ([OTHER], 0), (PLAN[:1], 1), ([OTHER, *PLAN[:2]], 2),
    (PLAN, 3), ([OTHER, *PLAN, _entry("later", 3)], 3),
])
def test_exact_prefix_and_complete_readonly_replay(observed, count):
    assert resume_prefix_length(PLAN, observed) == count


@pytest.mark.parametrize("observed", [
    [PLAN[1]], [PLAN[0], PLAN[2]], [PLAN[0], OTHER], [PLAN[0], OTHER, PLAN[1]],
    [_entry("intent", "changed")], [PLAN[0], _entry("first", True)],
    [PLAN[0], _entry("first", 1.0)], [PLAN[0], PLAN[0]],
])
def test_conflict_interleaving_and_loose_json_equality_block(observed):
    with pytest.raises(ValueError):
        resume_prefix_length(PLAN, observed)


def test_changed_intent_cannot_replace_missing_suffix():
    changed = [_entry("intent", "different-plan"), PLAN[1], _entry("second", 99)]
    with pytest.raises(ValueError, match="immutable event"):
        resume_prefix_length(changed, PLAN[:1])


def test_invalid_plan_preflight_even_if_journal_empty():
    for plan in ([], [PLAN[0], PLAN[0]], [_entry("", 1)], [_entry("nan", float("nan"))]):
        with pytest.raises(ValueError):
            resume_prefix_length(plan, [])
