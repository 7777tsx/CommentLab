from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.schemas import (
    AudiencePlan,
    CommentAction,
    PersonaSpec,
    SimulationConfig,
    normalize_ratios,
)


def test_post_is_limited_to_500_characters() -> None:
    with pytest.raises(ValidationError):
        SimulationConfig(post_text="文" * 501)


def test_blank_post_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SimulationConfig(post_text="   ")


def test_comment_action_requires_10_to_60_characters() -> None:
    with pytest.raises(ValidationError):
        CommentAction(persona_id="p", action="comment", text="太短")
    action = CommentAction(
        persona_id="p",
        action="comment",
        text="这是一条长度符合要求的模拟评论内容。",
    )
    assert action.action == "comment"


def test_ratios_are_normalized() -> None:
    result = normalize_ratios({"粉丝": 20, "路人": 30, "理性": 50})
    assert sum(result.values()) == pytest.approx(1.0)
    assert result["理性"] == pytest.approx(0.5)


def test_zero_ratios_fall_back_to_equal_distribution() -> None:
    result = normalize_ratios({"粉丝": 0, "路人": 0})
    assert result == {"粉丝": 0.5, "路人": 0.5}


def test_audience_normalizes_group_and_persona_weights() -> None:
    personas = [
        PersonaSpec(
            persona_id="a",
            label="A",
            group_name="粉丝",
            description="A persona",
            weight=1,
        ),
        PersonaSpec(
            persona_id="b",
            label="B",
            group_name="粉丝",
            description="B persona",
            weight=3,
        ),
    ]
    plan = AudiencePlan(personas=personas, group_ratios={"粉丝": 100}, rationale="test").normalized()
    assert sum(persona.weight for persona in plan.personas) == pytest.approx(1.0)
    assert plan.personas[1].weight == pytest.approx(0.75)

