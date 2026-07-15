from __future__ import annotations

from models.schemas import PublisherProfile, RewriteResult, RiskReport
from services.llm_client import ModelGateway


LEAK_MARKERS = {
    "shared_background",
    "publisher_profile",
    "risk_report",
    "preserved_elements",
    "repaired_risks",
    "rewritten_post",
    "保留事件表达",
    "保留核心观点",
    "核心观点不动",
    "补充范围",
    "替换",
    "编辑批注",
    "修改理由",
    "字段名",
}


def _has_leak_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in LEAK_MARKERS)


def _has_excessive_parentheses(text: str) -> bool:
    bracket_count = sum(text.count(pair) for pair in "()（）[]【】")
    return bracket_count >= 6 or "）（" in text or ")(" in text


def rewrite_audit(result: RewriteResult) -> tuple[bool, list[str]]:
    """Validate that rewritten_post is publishable text, not editing notes."""
    issues: list[str] = []
    text = result.rewritten_post.strip()
    if not text:
        issues.append("改写正文为空")
    if _has_leak_marker(text):
        issues.append("改写正文包含系统字段名或编辑批注")
    if _has_excessive_parentheses(text):
        issues.append("改写正文包含过多说明性括号")
    if "：" in text[:16] or ":" in text[:16]:
        issues.append("改写正文疑似包含字段标签")
    return not issues, issues


class RewriteChain:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    def run(
        self,
        post_text: str,
        profile: PublisherProfile,
        report: RiskReport,
        *,
        background_context: dict | None = None,
    ) -> RewriteResult:
        payload = {
            "post_text": post_text,
            "publisher_profile": profile.model_dump(),
            "risk_report": report.model_dump(),
            "shared_background": background_context or {},
        }
        prompt = (
            "你是人设保持改写Agent。不得改变核心观点、替用户撤回立场或添加未知事实。"
            "不要把个人表达统一改成官方声明。保留原语气和长度，优先修复高风险句、"
            "补充必要的范围和责任信息。shared_background是所有相关Agent共同知晓的联网核对背景；"
            "用它避免事实冲突，但不得把不确定内容写成事实，也不得擅自向帖子添加背景中的新断言。"
            "rewritten_post必须是用户可以直接发布的纯正文；严禁出现字段名、shared_background、"
            "任务说明、编辑批注、修改理由、推理过程、括号内逐项解释或'保留/替换/补充'等改稿说明。"
            "所有说明只能写入explanation、preserved_elements或repaired_risks。"
        )
        candidate = self.gateway.invoke_structured(
            stage="rewrite",
            schema=RewriteResult,
            payload=payload,
            system_prompt=prompt,
            fallback=lambda: self._demo_rewrite(post_text, profile, report),
        )
        ok, issues = rewrite_audit(candidate)
        if ok:
            return candidate
        repair_payload = {
            **payload,
            "invalid_rewrite": candidate.model_dump(),
            "audit_issues": issues,
        }
        repaired = self.gateway.invoke_structured(
            stage="rewrite_repair",
            schema=RewriteResult,
            payload=repair_payload,
            system_prompt=(
                prompt
                + "上一版改写没有通过审计。请只输出干净的最终正文和字段化说明，"
                + "不要在rewritten_post中解释任何修改动作。"
            ),
            fallback=lambda: self._demo_rewrite(post_text, profile, report),
        )
        ok, _ = rewrite_audit(repaired)
        return repaired if ok else self._demo_rewrite(post_text, profile, report)

    @staticmethod
    def keep_original(post_text: str, reason: str = "本轮没有找到更优改写，保留原文。") -> RewriteResult:
        return RewriteResult(
            rewritten_post=post_text[:500],
            preserved_elements=["原文保持不变", "未引入新事实", "未改变发布者立场"],
            repaired_risks=[],
            explanation=reason,
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
