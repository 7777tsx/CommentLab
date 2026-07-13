from __future__ import annotations

from models.schemas import PublisherProfile, RewriteResult, RiskReport
from services.llm_client import ModelGateway


class RewriteChain:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    def run(
        self,
        post_text: str,
        profile: PublisherProfile,
        report: RiskReport,
    ) -> RewriteResult:
        payload = {
            "post_text": post_text,
            "publisher_profile": profile.model_dump(),
            "risk_report": report.model_dump(),
        }
        return self.gateway.invoke_structured(
            stage="rewrite",
            schema=RewriteResult,
            payload=payload,
            system_prompt=(
                "你是人设保持改写Agent。不得改变核心观点、替用户撤回立场或添加未知事实。"
                "不要把个人表达统一改成官方声明。保留原语气和长度，优先修复高风险句、"
                "补充必要的范围和责任信息。"
            ),
            fallback=lambda: self._demo_rewrite(post_text, profile, report),
        )

    @staticmethod
    def _demo_rewrite(
        post_text: str, profile: PublisherProfile, report: RiskReport
    ) -> RewriteResult:
        if "减少更新" in post_text or "降低更新" in post_text:
            rewritten = "最近我会暂时减少一些更新，具体安排确定后会及时告诉大家，也谢谢大家理解。"
        elif "有些人" in post_text or "指手画脚" in post_text:
            rewritten = "我希望讨论时能尊重彼此，也希望大家针对具体事情表达意见，少一些越界的指点。"
        elif "处理得不够好" in post_text or "不要只看结果" in post_text:
            rewritten = "这件事确实是我处理得不够好，我接受大家对结果的批评。关于当时的情况，我会在不回避责任的前提下补充说明。"
        else:
            rewritten = post_text
            replacements = {
                "有些人": "部分越界行为",
                "大家不用多想": "后续有明确安排时我会及时说明",
                "不要只看结果": "我会先承担结果，再补充必要背景",
            }
            for source, target in replacements.items():
                rewritten = rewritten.replace(source, target)
            if rewritten == post_text:
                rewritten = f"{post_text.rstrip('。')}。这里针对的是具体行为和当前情况，不是对某类人的概括。"
        return RewriteResult(
            rewritten_post=rewritten[:500],
            preserved_elements=["原始核心观点", f"发布者“{profile.style}”的表达风格", "个人表达口吻"],
            repaired_risks=[span.reason for span in report.risky_spans[:3]],
            explanation="改写保留原立场，明确对象和范围，并将容易否定受众感受的表达改为可验证的信息。",
        )

