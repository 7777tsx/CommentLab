from __future__ import annotations

from evaluation.runner import (
    EXPECTED_IDS,
    build_business_input,
    keyword_group_coverage,
    load_dataset,
    span_coverage,
)


def test_evaluation_dataset_has_30_contiguous_ids() -> None:
    dataset = load_dataset()
    assert [case["id"] for case in dataset["cases"]] == EXPECTED_IDS


def test_user_real_cases_are_grouped_first() -> None:
    cases = load_dataset()["cases"]
    assert all(case["source_type"] == "real" for case in cases[:7])
    assert all(case["source_type"] == "synthetic" for case in cases[7:])


def test_hidden_comments_never_enter_business_input() -> None:
    case = load_dataset()["cases"][0]
    business_input = build_business_input(case)
    serialized = str(business_input)
    assert "annotations" not in business_input
    assert "real_comments" not in business_input
    assert case["annotations"]["real_comments"][0] not in serialized


def test_real_cases_use_fixed_background_without_web() -> None:
    cases = load_dataset()["cases"][:7]
    assert all(case["background"]["status"] == "completed" for case in cases)
    assert all(case["search_background"] is False for case in cases)


def test_keyword_group_coverage_reports_evidence() -> None:
    groups = [
        {"label": "体育政治", "keywords": ["体育与政治", "政治"]},
        {"label": "处罚", "keywords": ["红牌", "处罚"]},
    ]
    ratio, details = keyword_group_coverage(groups, "有人认为体育与政治无法彻底切割。")
    assert ratio == 0.5
    assert details[0]["matched_keyword"] == "体育与政治"
    assert details[1]["matched"] is False


def test_span_coverage_accepts_literal_subspan() -> None:
    ratio, details = span_coverage(["有没有认真工作"], ["认真工作"])
    assert ratio == 1.0
    assert details[0]["matched"] is True
