from __future__ import annotations

import re

from models.schemas import (
    ContentAnalysis,
    MisunderstandingChain,
    RiskReport,
    RiskScores,
    RiskySpan,
    SimulationResult,
)
from services.llm_client import ModelGateway


def risk_level(score: float) -> str:
    if score < 2.5:
        return "低"
    if score < 3.1:
        return "中"
    return "高"


def final_risk_score(text_analysis_score: float, simulation_score: float) -> float:
    return round(text_analysis_score * 0.25 + simulation_score * 0.75, 3)


def _ratio_band(value: float) -> int:
    """Convert an observable 0-1 ratio to a stable five-point band."""
    if value < 0.10:
        return 1
    if value < 0.25:
        return 2
    if value < 0.45:
        return 3
    if value < 0.65:
        return 4
    return 5


def deterministic_simulation_scores(simulation: SimulationResult) -> RiskScores:
    """Calculate risk components from comments and interaction structure."""
    comments = simulation.comments
    if not comments:
        return RiskScores(
            misunderstanding_risk=1,
            negative_emotion_risk=1,
            conflict_risk=1,
            off_topic_risk=1,
        )

    size = len(comments)
    replies = [comment for comment in comments if comment.parent_id]
    late_comments = [comment for comment in comments if comment.round_no > 1]
    late_misunderstanding = (
        sum(comment.misunderstanding for comment in late_comments) / len(late_comments)
        if late_comments
        else 0.0
    )
    average_intensity = sum(comment.emotion_intensity for comment in comments) / size
    average_controversy = sum(comment.controversy for comment in comments) / size
    conflict_ratio = min(
        1.0,
        simulation.metrics.conflict_reply_count / max(1, len(replies)),
    )

    misunderstanding_signal = (
        simulation.metrics.misunderstanding_ratio * 0.75
        + late_misunderstanding * 0.25
    )
    negative_signal = (
        simulation.metrics.negative_ratio * 0.70 + average_intensity * 0.30
    )
    conflict_signal = conflict_ratio * 0.65 + average_controversy * 0.35
    return RiskScores(
        misunderstanding_risk=_ratio_band(misunderstanding_signal),
        negative_emotion_risk=_ratio_band(negative_signal),
        conflict_risk=_ratio_band(conflict_signal),
        off_topic_risk=_ratio_band(simulation.metrics.off_topic_ratio),
    )


class RiskChain:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    def run(
        self,
        post_text: str,
        analysis: ContentAnalysis,
        simulation: SimulationResult,
        *,
        background_context: dict | None = None,
    ) -> RiskReport:
        payload = {
            "post_text": post_text,
            "analysis": analysis.model_dump(),
            "simulation_metrics": simulation.metrics.model_dump(),
            "comments": [comment.model_dump() for comment in simulation.comments],
            "shared_background": background_context or {},
            "scoring_rule": "文本25%，模拟75%；四类风险权重40/30/20/10",
        }
        candidate = self.gateway.invoke_structured(
            stage=f"risk_{simulation.config.version}",
            schema=RiskReport,
            payload=payload,
            system_prompt=(
                "你是沟通风险诊断Agent。结合原文分析和模拟评论识别误解、负面情绪、冲突、跑题。"
                "必须把风险归因到原文片段并提供误解链和修改方向，不判断事实或立场对错。"
                "shared_background是所有相关Agent共同知晓的联网核对背景；用它区分已知背景与无依据猜测，"
                "但不因事件事实本身给观点定性，且不得把不确定信息当成既定事实。"
                "misunderstanding_chains中的每一项必须包含source_span和steps："
                "source_span必须逐字复制post_text中的一段连续原文；"
                "steps填写从该片段出发的2至4个推导节点，不得重复source_span；"
                "每个step必须是语义完整的推导，不得输出‘读者将’‘进而接受’等连接词残片。"
                "内部评分为1到5。最终分严格按文本25%、模拟75%计算。"
            ),
            fallback=lambda: self._demo_report(post_text, analysis, simulation),
        )
        candidate = self._ensure_anchored_chains(post_text, candidate)
        # Scoring is a deterministic product rule, never delegated to model arithmetic.
        risk_scores = deterministic_simulation_scores(simulation)
        simulation_score = risk_scores.weighted_score()
        final_score = final_risk_score(analysis.text_analysis_score, simulation_score)
        return candidate.model_copy(
            update={
                "overall_level": risk_level(final_score),
                "risk_scores": risk_scores,
                "text_analysis_score": analysis.text_analysis_score,
                "simulation_score": simulation_score,
                "final_score": final_score,
            }
        )

    @staticmethod
    def _merge_fragmented_steps(steps: list[str]) -> list[str]:
        """Merge connector-only model fragments into complete inference nodes."""
        connector_end = re.compile(
            r"(?:将|把|被|为|成为|改为|视为|认为|接受|导致|引发|使|让|令|由于|因为|意味着)$"
        )
        transition_start = re.compile(r"^(?:进而|从而|最终|随后|继而|因此|于是)")
        continuation_start = re.compile(r"^[，。、；：的地得而与及并或]")
        merged = []
        pending = ""
        for raw in steps:
            step = re.sub(r"\s+", " ", str(raw)).strip()
            if not step:
                continue
            if pending:
                if transition_start.match(step) and len(pending) >= 10:
                    merged.append(pending)
                    pending = step if connector_end.search(step) else ""
                    if not pending:
                        merged.append(step)
                else:
                    pending += step
                    if re.search(r"[。！？；]$", pending):
                        merged.append(pending)
                        pending = ""
                continue
            if connector_end.search(step):
                pending = step
            elif continuation_start.match(step) and merged:
                merged[-1] += step
            else:
                merged.append(step)
        if pending:
            merged.append(pending)
        return merged

    @staticmethod
    def _ensure_anchored_chains(post_text: str, report: RiskReport) -> RiskReport:
        """Ensure every retained chain is anchored to a literal span of this post."""
        literal_risky_spans = [
            span.text.strip()
            for span in report.risky_spans
            if span.text.strip() and span.text.strip() in post_text
        ]
        anchored = []
        for chain in report.misunderstanding_chains:
            steps = RiskChain._merge_fragmented_steps(chain.steps)[:6]
            if not steps:
                continue
            source_span = chain.source_span.strip().strip("“”\"'")
            if source_span not in post_text:
                chain_key = re.sub(r"\s+", "", " ".join([source_span, *steps]))
                source_span = next(
                    (
                        span
                        for span in literal_risky_spans
                        if re.sub(r"\s+", "", span) in chain_key
                    ),
                    "",
                )
            if not source_span or source_span not in post_text:
                continue
            anchored.append(MisunderstandingChain(source_span=source_span, steps=steps))

        if not anchored:
            source_span = literal_risky_spans[0] if literal_risky_spans else post_text[:30]
            anchored = [
                MisunderstandingChain(
                    source_span=source_span,
                    steps=[
                        "该片段存在解释空间",
                        "不同受众自行补全含义",
                        "高热互动可能放大偏离原意的解读",
                    ],
                )
            ]
        return report.model_copy(update={"misunderstanding_chains": anchored})

    @staticmethod
    def _demo_report(
        post_text: str, analysis: ContentAnalysis, simulation: SimulationResult
    ) -> RiskReport:
        metrics = simulation.metrics
        misunderstanding = max(1, min(5, 1 + round(metrics.misunderstanding_ratio * 5)))
        negative = max(1, min(5, 1 + round(metrics.negative_ratio * 4)))
        conflict = max(1, min(5, 1 + min(4, metrics.conflict_reply_count)))
        off_topic = max(1, min(5, 1 + round(metrics.off_topic_ratio * 5)))
        scores = RiskScores(
            misunderstanding_risk=misunderstanding,
            negative_emotion_risk=negative,
            conflict_risk=conflict,
            off_topic_risk=off_topic,
        )
        simulation_score = scores.weighted_score()
        final_score = final_risk_score(analysis.text_analysis_score, simulation_score)
        risky_spans = [
            RiskySpan(text=issue.text, reason=issue.reason)
            for issue in analysis.ambiguous_phrases + analysis.emotional_phrases
        ][:4]
        if not risky_spans:
            risky_spans = [RiskySpan(text=post_text[:30], reason="表达信息有限，不同受众可能采用不同解释")]
        chains = []
        for misreading in analysis.possible_misreadings[:3]:
            anchor = risky_spans[0].text
            chains.append(
                MisunderstandingChain(
                    source_span=anchor,
                    steps=[
                        "信息不足",
                        "受众补全含义",
                        f"形成“{misreading}”解读",
                        "高热互动继续放大",
                    ],
                )
            )
        if not chains:
            chains = [
                MisunderstandingChain(
                    source_span=risky_spans[0].text,
                    steps=[
                        "信息缺口",
                        "不同Persona自行补全",
                        "高热评论影响后续阅读",
                        "讨论中心偏移",
                    ],
                )
            ]
        directions = [
            "明确表达涉及的对象、范围和时间边界",
            "将对人的概括改为对具体行为或事实的描述",
            "先回应受众最关心的信息，再补充背景说明",
            "保留原有语气，但删除会否定受众感受的命令式表达",
        ]
        return RiskReport(
            overall_level=risk_level(final_score),
            risk_scores=scores,
            text_analysis_score=analysis.text_analysis_score,
            simulation_score=simulation_score,
            final_score=final_score,
            risky_spans=risky_spans,
            misunderstanding_chains=chains,
            modification_directions=directions,
            summary=(
                f"模拟显示主要风险来自{risky_spans[0].text}的解释空间。"
                "部分受众会补全未说明的动机或范围，高热评论可能使这一解读成为主导叙事。"
            ),
        )
