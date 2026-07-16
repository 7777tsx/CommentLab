from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chains.rewrite_chain import rewrite_audit
from config import ROOT_DIR, settings
from models.schemas import (
    PreparedProject,
    ProjectResult,
    PublisherProfile,
    SimulationConfig,
    WebResearchResult,
)
from services.orchestrator import CommentLabOrchestrator


DEFAULT_DATASET = ROOT_DIR / "data" / "eval_cases.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "evaluation" / "results"
EXPECTED_IDS = [f"CL-EVAL-{index:03d}" for index in range(1, 31)]


def load_dataset(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise ValueError("评测集缺少 cases 数组")
    ids = [case.get("id") for case in cases]
    if ids != EXPECTED_IDS:
        raise ValueError(f"评测编号必须连续且唯一：{EXPECTED_IDS[0]} 至 {EXPECTED_IDS[-1]}")
    for index, case in enumerate(cases, start=1):
        validate_case(case, index)
    return dataset


def validate_case(case: dict[str, Any], index: int) -> None:
    required = {
        "id",
        "title",
        "source_type",
        "expected_risk",
        "search_background",
        "event_hint",
        "post_text",
        "profile",
        "annotations",
    }
    missing = sorted(required - case.keys())
    if missing:
        raise ValueError(f"第 {index} 条案例缺少字段：{', '.join(missing)}")
    if case["source_type"] not in {"real", "synthetic"}:
        raise ValueError(f"{case['id']} source_type 非法")
    if case["expected_risk"] not in {"低", "中", "高"}:
        raise ValueError(f"{case['id']} expected_risk 非法")
    if not 1 <= len(case["post_text"].strip()) <= 500:
        raise ValueError(f"{case['id']} 帖子长度不在 1 至 500 字范围内")
    real_comments = case["annotations"].get("real_comments", [])
    if case["source_type"] == "real" and not real_comments:
        raise ValueError(f"{case['id']} 现实案例缺少隐藏真实评论")
    if case["source_type"] == "real" and not case.get("background"):
        raise ValueError(f"{case['id']} 现实案例缺少固定背景卡")
    if case["source_type"] == "synthetic" and real_comments:
        raise ValueError(f"{case['id']} 自拟案例不应包含真实评论")


def build_business_input(case: dict[str, Any]) -> dict[str, Any]:
    """Return only fields allowed to enter the product pipeline.

    Gold annotations and real comments deliberately stay outside this object.
    """
    return {
        "post_text": case["post_text"],
        "profile": dict(case["profile"]),
        "search_background": bool(case["search_background"]),
        "event_hint": case["event_hint"],
        "background": case.get("background"),
    }


def prepare_case(
    orchestrator: CommentLabOrchestrator,
    business: dict[str, Any],
    *,
    no_web: bool,
) -> PreparedProject:
    """Prepare a case with fixed JSON background when present, avoiding web calls."""
    profile = PublisherProfile(**business["profile"])
    if not business.get("background"):
        return orchestrator.prepare(
            business["post_text"],
            profile,
            search_background=business["search_background"] and not no_web,
            event_hint=business["event_hint"],
        )

    research = WebResearchResult.model_validate(business["background"])
    background_context = orchestrator._shared_background(research)
    analysis, audience = orchestrator.preparation_chain.run(
        business["post_text"],
        profile,
        background_context=background_context,
    )
    return PreparedProject(
        post_text=business["post_text"],
        publisher_profile=profile,
        analysis=analysis,
        audience=audience,
        background_research=research,
    )


def normalize_text(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value).lower()


def keyword_group_coverage(
    groups: Iterable[dict[str, Any]], haystack: str
) -> tuple[float, list[dict[str, Any]]]:
    normalized_haystack = normalize_text(haystack)
    details = []
    for group in groups:
        keywords = [str(value) for value in group.get("keywords", []) if str(value).strip()]
        matched = next(
            (keyword for keyword in keywords if normalize_text(keyword) in normalized_haystack),
            None,
        )
        details.append(
            {
                "label": group.get("label", ""),
                "matched": matched is not None,
                "matched_keyword": matched,
            }
        )
    if not details:
        return 1.0, details
    return round(sum(item["matched"] for item in details) / len(details), 3), details


def span_coverage(expected_spans: list[str], predicted_spans: list[str]) -> tuple[float, list[dict[str, Any]]]:
    details = []
    normalized_predictions = [normalize_text(value) for value in predicted_spans]
    for expected in expected_spans:
        normalized_expected = normalize_text(expected)
        matched = None
        for raw, normalized in zip(predicted_spans, normalized_predictions):
            if not normalized or not normalized_expected:
                continue
            if normalized_expected in normalized or (
                len(normalized) >= 4 and normalized in normalized_expected
            ):
                matched = raw
                break
        details.append({"expected": expected, "matched": matched is not None, "prediction": matched})
    if not details:
        return 1.0, details
    return round(sum(item["matched"] for item in details) / len(details), 3), details


def result_text(result: ProjectResult, *, comments_only: bool = False) -> str:
    comments = "\n".join(comment.text for comment in result.simulation_before.comments)
    if comments_only:
        return comments
    analysis = result.analysis_before
    risk = result.risk_before
    fields = [
        comments,
        analysis.main_message,
        "\n".join(analysis.reasonable_disagreements),
        "\n".join(analysis.unsupported_inferences),
        "\n".join(analysis.audience_conflicts),
        "\n".join(analysis.possible_misreadings),
        risk.summary,
        "\n".join(span.reason for span in risk.risky_spans),
        "\n".join(risk.modification_directions),
        "\n".join(step for chain in risk.misunderstanding_chains for step in chain.steps),
    ]
    return "\n".join(fields)


def feedback_text(analysis, simulation, risk, *, comments_only: bool = False) -> str:
    comments = "\n".join(comment.text for comment in simulation.comments)
    if comments_only:
        return comments
    fields = [
        comments,
        analysis.main_message,
        "\n".join(analysis.reasonable_disagreements),
        "\n".join(analysis.unsupported_inferences),
        "\n".join(analysis.audience_conflicts),
        "\n".join(analysis.possible_misreadings),
        risk.summary,
        "\n".join(span.reason for span in risk.risky_spans),
        "\n".join(risk.modification_directions),
        "\n".join(step for chain in risk.misunderstanding_chains for step in chain.steps),
    ]
    return "\n".join(fields)


def unexpected_fact_tokens(original: str, rewritten: str) -> list[str]:
    """Catch newly introduced numbers and Latin identifiers; semantic review remains visible in report."""
    token_pattern = re.compile(r"(?:\d+(?:\.\d+)?%?|[A-Za-z][A-Za-z0-9_-]{2,})")
    original_tokens = {token.lower() for token in token_pattern.findall(original)}
    return sorted(
        {
            token
            for token in token_pattern.findall(rewritten)
            if token.lower() not in original_tokens
        }
    )


def structural_diagnostics(result: ProjectResult) -> dict[str, Any]:
    return structural_diagnostics_for(
        result.post_text, result.simulation_before.comments
    )


def structural_diagnostics_for(post_text: str, comments) -> dict[str, Any]:
    normalized = [normalize_text(comment.text) for comment in comments]
    duplicates = len(normalized) - len(set(normalized))
    invalid_evidence = [
        comment.comment_id
        for comment in comments
        if comment.evidence_span
        and comment.evidence_span not in post_text
        and not any(
            parent.comment_id == comment.parent_id and comment.evidence_span in parent.text
            for parent in comments
        )
    ]
    return {
        "comment_count": len(comments),
        "duplicate_comment_count": duplicates,
        "invalid_evidence_comment_ids": invalid_evidence,
        "persona_count": len({comment.persona_id for comment in comments}),
        "reaction_types": sorted({comment.reaction_type for comment in comments}),
    }


def evaluate_feedback_result(
    case, prepared, simulation, risk, rewrite, analysis_after
) -> dict[str, Any]:
    """Score original feedback plus text-only rewrite risk; no after-side simulation."""
    annotations = case["annotations"]
    predicted_spans = [span.text for span in risk.risky_spans]
    predicted_spans.extend(chain.source_span for chain in risk.misunderstanding_chains)
    risk_span_ratio, risk_span_details = span_coverage(
        annotations.get("risk_spans", []), predicted_spans
    )
    controversy_ratio, controversy_details = keyword_group_coverage(
        annotations.get("controversy_topics", []),
        feedback_text(prepared.analysis, simulation, risk),
    )
    preservation_ratio, preservation_details = keyword_group_coverage(
        annotations.get("preserved_points", []), rewrite.rewritten_post
    )
    clean_rewrite, rewrite_audit_issues = rewrite_audit(rewrite)
    invented_tokens = unexpected_fact_tokens(
        case["post_text"], rewrite.rewritten_post
    )
    expected_spans = annotations.get("risk_spans", [])
    risk_span_pass = (
        risk_span_ratio >= 0.5
        if expected_spans
        else risk.overall_level == "低" and len(predicted_spans) <= 2
    )
    points = {
        "risk_level": {
            "passed": risk.overall_level == case["expected_risk"],
            "expected": case["expected_risk"],
            "actual": risk.overall_level,
        },
        "risk_spans": {
            "passed": risk_span_pass,
            "coverage": risk_span_ratio,
            "details": risk_span_details,
        },
        "main_controversies": {
            "passed": controversy_ratio >= 0.5,
            "coverage": controversy_ratio,
            "details": controversy_details,
        },
        "rewrite_fidelity": {
            "passed": preservation_ratio >= 0.5 and clean_rewrite and not invented_tokens,
            "preservation_coverage": preservation_ratio,
            "details": preservation_details,
            "rewrite_audit_issues": rewrite_audit_issues,
            "unexpected_fact_tokens": invented_tokens,
        },
        "text_risk_reduction": {
            "passed": (
                analysis_after.text_analysis_score
                <= prepared.analysis.text_analysis_score
                if case["expected_risk"] == "低"
                else analysis_after.text_analysis_score
                < prepared.analysis.text_analysis_score
            ),
            "before_score": prepared.analysis.text_analysis_score,
            "after_score": analysis_after.text_analysis_score,
            "note": "只比较前后文本分析分；未对改写稿重做评论模拟。",
        },
    }
    real_metric = None
    if case["source_type"] == "real":
        real_ratio, real_details = keyword_group_coverage(
            annotations.get("controversy_topics", []),
            feedback_text(prepared.analysis, simulation, risk, comments_only=True),
        )
        real_metric = {
            "passed": real_ratio >= 0.5,
            "coverage": real_ratio,
            "details": real_details,
            "note": "真实评论未进入生成流程；本指标只对生成完成后的模拟评论做隐藏对照。",
        }
    return {
        "case_id": case["id"],
        "title": case["title"],
        "source_type": case["source_type"],
        "core_score": sum(int(item["passed"]) for item in points.values()),
        "core_total": 5,
        "points": points,
        "real_case_controversy_prediction": real_metric,
        "structural_diagnostics": structural_diagnostics_for(
            case["post_text"], simulation.comments
        ),
    }


def evaluate_result(case: dict[str, Any], result: ProjectResult) -> dict[str, Any]:
    annotations = case["annotations"]
    predicted_spans = [span.text for span in result.risk_before.risky_spans]
    predicted_spans.extend(chain.source_span for chain in result.risk_before.misunderstanding_chains)
    risk_span_ratio, risk_span_details = span_coverage(
        annotations.get("risk_spans", []), predicted_spans
    )
    controversy_ratio, controversy_details = keyword_group_coverage(
        annotations.get("controversy_topics", []), result_text(result)
    )
    preservation_ratio, preservation_details = keyword_group_coverage(
        annotations.get("preserved_points", []), result.rewrite.rewritten_post
    )
    clean_rewrite, rewrite_audit_issues = rewrite_audit(result.rewrite)
    invented_tokens = unexpected_fact_tokens(case["post_text"], result.rewrite.rewritten_post)

    expected_spans = annotations.get("risk_spans", [])
    if expected_spans:
        risk_span_pass = risk_span_ratio >= 0.5
    else:
        risk_span_pass = result.risk_before.overall_level == "低" and len(predicted_spans) <= 2

    if case["expected_risk"] == "低":
        reduction_pass = result.risk_after.final_score <= result.risk_before.final_score
    else:
        reduction_pass = result.risk_after.final_score < result.risk_before.final_score

    points = {
        "risk_level": {
            "passed": result.risk_before.overall_level == case["expected_risk"],
            "expected": case["expected_risk"],
            "actual": result.risk_before.overall_level,
        },
        "risk_spans": {
            "passed": risk_span_pass,
            "coverage": risk_span_ratio,
            "details": risk_span_details,
        },
        "main_controversies": {
            "passed": controversy_ratio >= 0.5,
            "coverage": controversy_ratio,
            "details": controversy_details,
        },
        "rewrite_fidelity": {
            "passed": preservation_ratio >= 0.5 and clean_rewrite and not invented_tokens,
            "preservation_coverage": preservation_ratio,
            "details": preservation_details,
            "rewrite_audit_issues": rewrite_audit_issues,
            "unexpected_fact_tokens": invented_tokens,
        },
        "risk_reduction": {
            "passed": reduction_pass,
            "before_level": result.risk_before.overall_level,
            "after_level": result.risk_after.overall_level,
            "before_score": result.risk_before.final_score,
            "after_score": result.risk_after.final_score,
        },
    }
    core_score = sum(int(item["passed"]) for item in points.values())

    real_metric = None
    if case["source_type"] == "real":
        real_ratio, real_details = keyword_group_coverage(
            annotations.get("controversy_topics", []),
            result_text(result, comments_only=True),
        )
        real_metric = {
            "passed": real_ratio >= 0.5,
            "coverage": real_ratio,
            "details": real_details,
            "note": "真实评论未进入生成流程；本指标只对生成完成后的模拟评论做隐藏对照。",
        }

    return {
        "case_id": case["id"],
        "title": case["title"],
        "source_type": case["source_type"],
        "core_score": core_score,
        "core_total": 5,
        "points": points,
        "real_case_controversy_prediction": real_metric,
        "structural_diagnostics": structural_diagnostics(result),
    }


def select_cases(
    cases: list[dict[str, Any]], ids: list[str] | None, limit: int | None
) -> list[dict[str, Any]]:
    if ids:
        wanted = set(ids)
        selected = [case for case in cases if case["id"] in wanted]
        missing = wanted - {case["id"] for case in selected}
        if missing:
            raise ValueError(f"未知案例编号：{', '.join(sorted(missing))}")
    else:
        selected = list(cases)
    return selected[:limit] if limit else selected


def markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# CommentLab 评测报告",
        "",
        f"- 运行时间：{summary['started_at']}",
        f"- 模式：{'DEMO_MODE' if summary['demo_mode'] else '真实模型'}",
        f"- 案例数：{summary['case_count']}",
        f"- 核心得分：{summary['core_points']}/{summary['core_total']}",
        f"- 现实案例评论争议预测：{summary['real_prediction_passed']}/{summary['real_prediction_total']}",
        "",
    ]
    if summary["feedback_only"]:
        lines.extend(
            [
                "| 案例 | 风险 | 风险句 | 争议 | 改写忠实 | 文本降险 | 核心分 | 现实评论争议 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
    else:
        lines.extend(
            [
                "| 案例 | 风险 | 风险句 | 争议 | 改写 | 降险 | 核心分 | 现实评论争议 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
    for item in summary["results"]:
        point = item["points"]
        marks = ["✓" if point[name]["passed"] else "✗" for name in point]
        real = item["real_case_controversy_prediction"]
        real_mark = "—" if real is None else ("✓" if real["passed"] else "✗")
        lines.append(
            f"| {item['case_id']} {item['title']} | {' | '.join(marks)} | "
            f"{item['core_score']}/{item['core_total']} | {real_mark} |"
        )
    lines.extend(
        [
            "",
            "> 现实案例的真实评论只在输出完成后用于最后一列的隐藏对照。关键词自动评分用于快速回归，具体命中证据请查看同目录 JSON。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.dataset)
    selected = select_cases(dataset["cases"], args.ids, args.limit)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    app_settings = replace(
        settings,
        demo_mode=True if args.demo else settings.demo_mode,
        database_path=output_dir / "evaluation_cache.db",
    )
    orchestrator = CommentLabOrchestrator(app_settings)
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    evaluations = []

    for position, case in enumerate(selected, start=1):
        business = build_business_input(case)
        print(f"[{position}/{len(selected)}] {case['id']} {case['title']}", flush=True)
        prepared = prepare_case(orchestrator, business, no_web=args.no_web)
        case_dir = output_dir / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        if args.feedback_only:
            audience = prepared.audience.normalized()
            config = SimulationConfig(
                post_text=prepared.post_text,
                version="before",
                seed=args.seed,
                lurker_count=50,
                rounds=3,
                activation_counts=[7, 4, 3],
            )
            background_context = orchestrator._shared_background(
                prepared.background_research
            )
            simulation = orchestrator.simulation_engine.run(
                config,
                prepared.publisher_profile,
                audience,
                prepared.analysis,
                background_context=background_context,
            )
            risk = orchestrator.risk_chain.run(
                prepared.post_text,
                prepared.analysis,
                simulation,
                background_context=background_context,
            )
            if orchestrator._should_skip_rewrite(risk):
                rewrite = orchestrator.rewrite_chain.keep_original(
                    prepared.post_text,
                    "原文已是低风险，轻量评测不强制改写。",
                )
                analysis_after = prepared.analysis
            else:
                rewrite = orchestrator.rewrite_chain.run(
                    prepared.post_text,
                    prepared.publisher_profile,
                    risk,
                    background_context=background_context,
                )
                analysis_after = orchestrator.content_chain.run(
                    rewrite.rewritten_post,
                    prepared.publisher_profile,
                    background_context=background_context,
                )
            feedback_result = {
                "prepared": prepared.model_dump(),
                "simulation_before": simulation.model_dump(),
                "risk_before": risk.model_dump(),
                "rewrite": rewrite.model_dump(),
                "analysis_after": analysis_after.model_dump(),
            }
            (case_dir / "feedback_result.json").write_text(
                json.dumps(feedback_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            evaluation = evaluate_feedback_result(
                case, prepared, simulation, risk, rewrite, analysis_after
            )
        else:
            result = orchestrator.complete(prepared, seed=args.seed)
            (case_dir / "project_result.json").write_text(
                result.model_dump_json(indent=2), encoding="utf-8"
            )
            evaluation = evaluate_result(case, result)
        (case_dir / "evaluation.json").write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        evaluations.append(evaluation)
        real = evaluation["real_case_controversy_prediction"]
        real_text = "" if real is None else f", 现实争议覆盖 {real['coverage']:.0%}"
        print(
            f"  -> {evaluation['core_score']}/{evaluation['core_total']}{real_text}",
            flush=True,
        )

    real_metrics = [
        item["real_case_controversy_prediction"]
        for item in evaluations
        if item["real_case_controversy_prediction"] is not None
    ]
    summary = {
        "dataset_version": dataset.get("version", ""),
        "started_at": started_at,
        "demo_mode": orchestrator.demo_mode,
        "case_count": len(evaluations),
        "feedback_only": args.feedback_only,
        "core_points": sum(item["core_score"] for item in evaluations),
        "core_total": sum(item["core_total"] for item in evaluations),
        "real_prediction_passed": sum(int(item["passed"]) for item in real_metrics),
        "real_prediction_total": len(real_metrics),
        "results": evaluations,
    }
    (output_dir / "latest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "latest_report.md").write_text(markdown_report(summary), encoding="utf-8")
    print(
        f"完成：核心得分 {summary['core_points']}/{summary['core_total']}，"
        f"现实案例争议预测 {summary['real_prediction_passed']}/{summary['real_prediction_total']}",
        flush=True,
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 CommentLab 30 条简化评测集")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--ids", nargs="+", help="只运行指定编号，例如 CL-EVAL-001")
    parser.add_argument("--limit", type=int, help="从所选案例中只运行前 N 条")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--demo", action="store_true", help="强制使用确定性的 DEMO_MODE")
    parser.add_argument("--no-web", action="store_true", help="关闭案例配置的联网背景核对")
    parser.add_argument(
        "--feedback-only",
        action="store_true",
        help="测试原文反馈并比较改写前后文本风险，不对改写稿重做评论模拟",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
