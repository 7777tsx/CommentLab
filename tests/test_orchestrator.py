from __future__ import annotations

import json
from pathlib import Path

import pytest


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def persona_signature(simulation) -> tuple:
    return (
        tuple(
            sorted(
                (
                    persona.persona_id,
                    persona.group_name,
                    round(persona.weight, 8),
                    persona.reading_depth,
                    persona.trust,
                    persona.emotion_sensitivity,
                    persona.controversy_tendency,
                    persona.influence,
                )
                for persona in simulation.audience.personas
            )
        ),
        simulation.config.seed,
        simulation.config.lurker_count,
        simulation.config.rounds,
        tuple(simulation.config.activation_counts),
    )


def test_counterfactual_uses_identical_audience(orchestrator, profile) -> None:
    prepared = orchestrator.prepare("有些人真的应该学会尊重别人，不要什么事情都来指手画脚。", profile)
    result = orchestrator.complete(prepared, seed=99)
    assert persona_signature(result.simulation_before) == persona_signature(result.simulation_after)
    assert result.comparison.persona_consistency is True
    assert result.simulation_before.config.post_text != result.simulation_after.config.post_text


def test_audience_is_restricted_to_report_personas(orchestrator) -> None:
    default = orchestrator.audience_chain._default_plan()
    polluted = default.model_copy(deep=True)
    polluted.personas[0].persona_id = "invented_persona"
    cleaned = orchestrator.audience_chain._sanitize_plan(polluted)
    assert len(cleaned.personas) == 12
    assert "invented_persona" not in {persona.persona_id for persona in cleaned.personas}


def test_prepare_uses_one_combined_model_stage(orchestrator, profile) -> None:
    stages = []
    original = orchestrator.gateway.invoke_structured

    def record_stage(**kwargs):
        stages.append(kwargs["stage"])
        return original(**kwargs)

    orchestrator.gateway.invoke_structured = record_stage
    prepared = orchestrator.prepare("我们将在下周公布活动的具体安排。", profile)
    assert stages == ["preparation"]
    assert prepared.analysis.main_message
    assert len(prepared.audience.personas) == 12


@pytest.mark.parametrize("case_index", [0, 1, 2])
def test_all_demo_cases_complete_end_to_end(orchestrator, profile, case_index: int) -> None:
    cases = json.loads((DATA_DIR / "demo_cases.json").read_text(encoding="utf-8"))
    prepared = orchestrator.prepare(cases[case_index]["post_text"], profile)
    result = orchestrator.complete(prepared)
    assert 12 <= len(result.simulation_before.comments) <= 20
    assert 12 <= len(result.simulation_after.comments) <= 20
    assert result.rewrite.rewritten_post != result.post_text
    assert result.comparison.persona_consistency is True
    assert result.risk_before.overall_level in {"低", "中", "高"}
    assert result.risk_after.overall_level in {"低", "中", "高"}
    assert len({comment.text for comment in result.simulation_after.comments}) >= 8
