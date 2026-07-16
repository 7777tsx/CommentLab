from __future__ import annotations

import re

from models.schemas import PublisherProfile, RepairCheck, RewriteResult, RiskReport
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


def build_repair_targets(post_text: str, report: RiskReport) -> list[dict]:
    """Turn anchored risk spans and chains into explicit, auditable rewrite tasks."""
    chain_steps: dict[str, list[str]] = {}
    for chain in report.misunderstanding_chains:
        span = chain.source_span.strip()
        if span and span in post_text:
            chain_steps.setdefault(span, []).extend(chain.steps)

    candidates: list[tuple[str, str]] = []
    for span in report.risky_spans:
        text = span.text.strip()
        if text and text in post_text:
            candidates.append((text, span.reason.strip()))
    for source_span, steps in chain_steps.items():
        if source_span not in {text for text, _reason in candidates}:
            candidates.append((source_span, "；".join(steps[:3])))

    targets = []
    seen = set()
    for source_span, reason in candidates:
        if source_span in seen:
            continue
        seen.add(source_span)
        combined = reason + "；" + "；".join(chain_steps.get(source_span, [])[:3])
        if any(
            marker in combined
            for marker in ("指责", "攻击", "侮辱", "贬损", "否定", "命令", "归因", "动机", "绝对")
        ):
            action = "remove_or_reframe"
        elif any(marker in combined for marker in ("模糊", "范围", "指代", "缺失", "不明确", "信息")):
            action = "clarify"
        else:
            action = "qualify"
        targets.append(
            {
                "target_id": f"risk_{len(targets) + 1}",
                "source_span": source_span,
                "reason": reason or "该片段可能引发沟通风险",
                "misunderstanding_steps": chain_steps.get(source_span, [])[:4],
                "required_action": action,
                "must_change_literal": len(re.sub(r"\s+", "", source_span)) >= 4,
            }
        )
        if len(targets) >= 6:
            break
    return targets


def _disclaimer_only(text: str, source_span: str) -> bool:
    if source_span not in text:
        return False
    tail = text[text.find(source_span) + len(source_span) :]
    return any(
        marker in tail[:80]
        for marker in ("不是对", "并不是对", "并非针对", "不代表我", "没有指责", "只是自我", "仅代表")
    )


def rewrite_audit(
    result: RewriteResult,
    post_text: str | None = None,
    repair_targets: list[dict] | None = None,
) -> tuple[bool, list[str]]:
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
    for target in repair_targets or []:
        source_span = target["source_span"]
        if target.get("must_change_literal") and source_span in text:
            issues.append(f"风险目标“{source_span}”仍被逐字保留")
        if _disclaimer_only(text, source_span):
            issues.append(f"风险目标“{source_span}”仅追加免责声明，没有修复原表达")
    if post_text and text == post_text and repair_targets:
        issues.append("改写与原文完全相同，风险链未得到修复")
    return not issues, issues


def _attach_repair_checks(
    result: RewriteResult, repair_targets: list[dict]
) -> RewriteResult:
    checks = []
    for target in repair_targets:
        source_span = target["source_span"]
        unchanged = target.get("must_change_literal") and source_span in result.rewritten_post
        disclaimer_only = _disclaimer_only(result.rewritten_post, source_span)
        resolved = not unchanged and not disclaimer_only
        checks.append(
            RepairCheck(
                target_id=target["target_id"],
                source_span=source_span,
                required_action=target["required_action"],
                resolved=resolved,
                explanation=(
                    "原风险表达已被删除或重新组织。"
                    if resolved
                    else "原风险表达仍然存在，或只在后面增加了免责声明。"
                ),
            )
        )
    return result.model_copy(update={"repair_checks": checks})


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
        repair_targets = build_repair_targets(post_text, report)
        payload = {
            "post_text": post_text,
            "publisher_profile": profile.model_dump(),
            "risk_report": report.model_dump(),
            "repair_targets": repair_targets,
            "shared_background": background_context or {},
        }
        prompt = (
            "你是人设保持改写Agent。不得改变核心观点、替用户撤回立场或添加未知事实。"
            "不要把个人表达统一改成官方声明。保留原语气和长度，优先修复高风险句、"
            "补充必要的范围和责任信息。必须按repair_targets逐项修复："
            "remove_or_reframe表示删除责任归因、人身评价或改写为对具体行为的描述；"
            "clarify表示明确对象和范围；qualify表示降低无依据的绝对断言。"
            "不得逐字保留高风险句后仅追加‘不是指责’‘仅代表个人’等免责声明；"
            "不得只在repaired_risks里声称修复而正文不变。"
            "shared_background是所有相关Agent共同知晓的联网核对背景；"
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
        candidate = _attach_repair_checks(candidate, repair_targets)
        ok, issues = rewrite_audit(candidate, post_text, repair_targets)
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
        repaired = _attach_repair_checks(repaired, repair_targets)
        ok, _ = rewrite_audit(repaired, post_text, repair_targets)
        if ok:
            return repaired
        fallback = self._demo_rewrite(post_text, profile, report)
        fallback = _attach_repair_checks(fallback, repair_targets)
        ok, _ = rewrite_audit(fallback, post_text, repair_targets)
        if ok:
            return fallback
        return self.keep_original(
            post_text,
            "候选改写未通过风险链逐项修复审计，已保留原文，避免输出表面降温但风险句未改变的文案。",
        )

    @staticmethod
    def keep_original(post_text: str, reason: str = "本轮没有找到更优改写，保留原文。") -> RewriteResult:
        return RewriteResult(
            rewritten_post=post_text[:500],
            preserved_elements=["原文保持不变", "未引入新事实", "未改变发布者立场"],
            repaired_risks=[],
            explanation=reason,
            repair_checks=[],
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
                "有没有认真工作": "不同人的收入和消费压力各不相同",
                "工资涨没涨": "每个人的收入变化并不相同",
                "找找自己原因": "也可以结合自己的实际情况判断是否适合购买",
            }
            for source, target in replacements.items():
                rewritten = rewritten.replace(source, target)
            if rewritten == post_text:
                for span in report.risky_spans[:3]:
                    if len(re.sub(r"\s+", "", span.text)) >= 4:
                        rewritten = rewritten.replace(span.text, "对这件事更具体、有限的看法")
            if rewritten == post_text:
                rewritten = post_text
        return RewriteResult(
            rewritten_post=rewritten[:500],
            preserved_elements=["原始核心观点", f"发布者“{profile.style}”的表达风格", "个人表达口吻"],
            repaired_risks=[span.reason for span in report.risky_spans[:3]],
            explanation="改写保留原立场，明确对象和范围，并将容易否定受众感受的表达改为可验证的信息。",
        )
