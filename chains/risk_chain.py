from __future__ import annotations

from models.schemas import (
    ContentAnalysis,
    RiskReport,
    RiskScores,
    RiskySpan,
    SimulationResult,
)
from services.llm_client import ModelGateway


def risk_level(score: float) -> str:
    if score < 2.0:
        return "低"
    if score < 3.5:
        return "中"
    return "高"


def final_risk_score(text_analysis_score: float, simulation_score: float) -> float:
    return round(text_analysis_score * 0.25 + simulation_score * 0.75, 3)


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
                "内部评分为1到5。最终分严格按文本25%、模拟75%计算。"
            ),
            fallback=lambda: self._demo_report(post_text, analysis, simulation),
        )
        # Scoring is a deterministic product rule, never delegated to model arithmetic.
        simulation_score = candidate.risk_scores.weighted_score()
        final_score = final_risk_score(analysis.text_analysis_score, simulation_score)
        return candidate.model_copy(
            update={
                "overall_level": risk_level(final_score),
                "text_analysis_score": analysis.text_analysis_score,
                "simulation_score": simulation_score,
                "final_score": final_score,
            }
        )

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
            chains.append(f"“{anchor}”信息不足 → 受众补全含义 → 形成“{misreading}”解读 → 高热互动继续放大")
        if not chains:
            chains = ["信息缺口 → 不同Persona自行补全 → 高热评论影响后续阅读 → 讨论中心偏移"]
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
