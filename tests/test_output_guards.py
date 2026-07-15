from __future__ import annotations

from chains.content_analysis_chain import ContentAnalysisChain
from chains.rewrite_chain import rewrite_audit
from models.schemas import (
    ContentAnalysis,
    PhraseIssue,
    RewriteResult,
    RiskReport,
    RiskScores,
)
from services.orchestrator import CommentLabOrchestrator


def make_report(score: float, level: str) -> RiskReport:
    return RiskReport(
        overall_level=level,
        risk_scores=RiskScores(
            misunderstanding_risk=2,
            negative_emotion_risk=2,
            conflict_risk=2,
            off_topic_risk=2,
        ),
        text_analysis_score=score,
        simulation_score=score,
        final_score=score,
        risky_spans=[],
        misunderstanding_chains=[],
        modification_directions=[],
        summary="test",
    )


def test_rewrite_audit_blocks_prompt_and_editorial_leaks() -> None:
    result = RewriteResult(
        rewritten_post="原文（保留事件表达受shared_background约束，为真）（补充范围说明）（核心观点不动）",
        preserved_elements=[],
        repaired_risks=[],
        explanation="说明可以放在这里",
    )
    ok, issues = rewrite_audit(result)
    assert ok is False
    assert any("字段名" in issue or "批注" in issue for issue in issues)


def test_rewrite_audit_allows_clean_publishable_text() -> None:
    result = RewriteResult(
        rewritten_post="我理解大家对这件事的关注，也会先把已经确认的情况说清楚。",
        preserved_elements=[],
        repaired_risks=[],
        explanation="保留原立场并减少误解空间。",
    )
    assert rewrite_audit(result)[0] is True


def test_content_analysis_sanitizer_keeps_only_source_phrases(profile) -> None:
    post_text = "好像已经成为一种潮流，我不太认同这种说法。"
    analysis = ContentAnalysis(
        main_message="表达对某种潮流的不认同",
        content_type="观点表达",
        tone="平静",
        ambiguous_phrases=[
            PhraseIssue(text="好像已经成为一种潮流", reason="没有说明潮流的具体范围和依据"),
            PhraseIssue(text="核心表达", reason="核心表达"),
            PhraseIssue(text="结合shared_background推断出的长段分析", reason="缺失信息"),
        ],
        missing_information=[],
        emotional_phrases=[],
        quotable_phrases=[],
        persona_conflicts=[],
        audience_conflicts=[],
        possible_misreadings=[],
        risk_scores=RiskScores(
            misunderstanding_risk=2,
            negative_emotion_risk=1,
            conflict_risk=1,
            off_topic_risk=1,
        ),
    )
    cleaned = ContentAnalysisChain._sanitize_analysis(analysis, post_text, profile)
    assert [issue.text for issue in cleaned.ambiguous_phrases] == ["好像已经成为一种潮流"]
    assert "具体范围" in cleaned.ambiguous_phrases[0].reason


def test_orchestrator_skips_low_risk_rewrite() -> None:
    assert CommentLabOrchestrator._should_skip_rewrite(make_report(1.8, "低")) is True
    assert CommentLabOrchestrator._should_skip_rewrite(make_report(2.4, "中")) is False


def test_orchestrator_rejects_non_improving_rewrite() -> None:
    before = make_report(2.6, "中")
    assert CommentLabOrchestrator._rewrite_improved(before, make_report(2.5, "中")) is True
    assert CommentLabOrchestrator._rewrite_improved(before, make_report(2.6, "中")) is False
    assert CommentLabOrchestrator._rewrite_improved(before, make_report(3.5, "高")) is False
