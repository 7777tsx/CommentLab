from __future__ import annotations

import pytest

from chains.risk_chain import final_risk_score, risk_level
from models.schemas import RiskScores


def test_four_risk_weights() -> None:
    scores = RiskScores(
        misunderstanding_risk=5,
        negative_emotion_risk=4,
        conflict_risk=3,
        off_topic_risk=2,
    )
    assert scores.weighted_score() == pytest.approx(4.0)


def test_final_score_uses_25_75_weighting() -> None:
    assert final_risk_score(2.0, 4.0) == pytest.approx(3.5)


@pytest.mark.parametrize(
    ("score", "expected"),
    [(2.499, "低"), (2.5, "中"), (3.099, "中"), (3.1, "高")],
)
def test_risk_thresholds(score: float, expected: str) -> None:
    assert risk_level(score) == expected
