from __future__ import annotations

from models.schemas import ComparisonReport, RiskReport, SimulationResult
from services.llm_client import ModelGateway


class ComparisonChain:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    def run(
        self,
        before: SimulationResult,
        after: SimulationResult,
        risk_before: RiskReport,
        risk_after: RiskReport,
        *,
        background_context: dict | None = None,
    ) -> ComparisonReport:
        consistent = self._persona_signature(before) == self._persona_signature(after)
        payload = {
            "before_metrics": before.metrics.model_dump(),
            "after_metrics": after.metrics.model_dump(),
            "risk_before": risk_before.model_dump(),
            "risk_after": risk_after.model_dump(),
            "persona_consistency": consistent,
            "shared_background": background_context or {},
        }
        candidate = self.gateway.invoke_structured(
            stage="comparison",
            schema=ComparisonReport,
            payload=payload,
            system_prompt=(
                "你是反事实对比Agent。比较同一受众和随机配置下改写前后的误解、负面情绪、"
                "对立回复和跑题变化。shared_background在前后模拟中完全一致，比较时只归因于帖子文本变化。"
                "不要把模拟结果表述为真实舆情概率，也不要把不确定背景当成事实。"
            ),
            fallback=lambda: self._demo_comparison(
                before, after, risk_before, risk_after, consistent
            ),
        )
        return candidate.model_copy(update={"persona_consistency": consistent})

    @staticmethod
    def _persona_signature(result: SimulationResult) -> tuple:
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
                    for persona in result.audience.personas
                )
            ),
            result.config.seed,
            result.config.lurker_count,
            result.config.rounds,
            tuple(result.config.activation_counts),
        )

    @staticmethod
    def _demo_comparison(
        before: SimulationResult,
        after: SimulationResult,
        risk_before: RiskReport,
        risk_after: RiskReport,
        consistent: bool,
    ) -> ComparisonReport:
        bm, am = before.metrics, after.metrics
        resolved = []
        if am.misunderstanding_ratio < bm.misunderstanding_ratio:
            resolved.append("由模糊范围和信息缺口引发的主要误解减少")
        if am.off_topic_ratio < bm.off_topic_ratio:
            resolved.append("玩梗或动机猜测带来的话题偏移减少")
        remaining = []
        if am.misunderstanding_ratio > 0:
            remaining.append("仍有少数受众希望获得更具体的时间或范围")
        if not remaining:
            remaining.append("当前模拟中没有形成持续的高频追问")
        improved = risk_after.final_score < risk_before.final_score
        return ComparisonReport(
            risk_before=risk_before.overall_level,
            risk_after=risk_after.overall_level,
            misunderstanding_change=round(am.misunderstanding_ratio - bm.misunderstanding_ratio, 3),
            negative_change=round(am.negative_ratio - bm.negative_ratio, 3),
            conflict_change=am.conflict_reply_count - bm.conflict_reply_count,
            off_topic_change=round(am.off_topic_ratio - bm.off_topic_ratio, 3),
            resolved_misreadings=resolved,
            remaining_questions=remaining,
            persona_consistency=consistent,
            conclusion=(
                "在相同受众和随机配置下，改写降低了主要沟通风险。"
                if improved
                else "改写尚未稳定降低模拟风险，仍需针对高风险片段继续修改。"
            ),
        )
