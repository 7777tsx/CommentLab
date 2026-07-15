from __future__ import annotations

from models.schemas import ContentAnalysis, PhraseIssue, PublisherProfile, RiskScores
from services.llm_client import ModelGateway


INTERNAL_LABELS = {
    "核心表达",
    "限定条件",
    "模糊词",
    "缺失信息",
    "内容类型",
    "语气",
    "潜在误解",
    "人设冲突",
    "合理分歧",
    "shared_background",
    "explicit_information",
    "unsupported_inferences",
}


def _contains_internal_label(value: str) -> bool:
    lowered = value.lower()
    return any(label.lower() in lowered for label in INTERNAL_LABELS)


def _clean_phrase_issues(issues: list[PhraseIssue], post_text: str) -> list[PhraseIssue]:
    cleaned: list[PhraseIssue] = []
    seen: set[str] = set()
    for issue in issues:
        phrase = issue.text.strip().strip("“”\"' ")
        reason = issue.reason.strip()
        if not phrase or phrase in seen:
            continue
        if phrase not in post_text:
            continue
        if len(phrase) > 30 or len(phrase) > max(12, len(post_text) // 2):
            continue
        if _contains_internal_label(phrase) or _contains_internal_label(reason):
            continue
        cleaned.append(PhraseIssue(text=phrase, reason=reason or "这句话的范围或依据还不够清楚"))
        seen.add(phrase)
    return cleaned[:5]


AMBIGUOUS_RULES = {
    "适当": "调整程度和边界不明确",
    "有些人": "指代范围不明确，多个群体可能对号入座",
    "大家": "受众范围过宽",
    "复杂": "没有说明哪些情况复杂，容易被理解为回避",
    "不用多想": "否定受众疑问，反而可能强化猜测",
    "不要只看结果": "容易被理解为要求受众降低对结果的关注",
}

EMOTIONAL_RULES = {
    "真的应该": "带有明显的责备和评判语气",
    "指手画脚": "容易让不同意见者感到被攻击",
    "不要": "命令式表达可能引发抵触",
    "但": "在道歉语境中可能削弱前面的责任表达",
}


class ContentAnalysisChain:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    def run(
        self,
        post_text: str,
        profile: PublisherProfile,
        *,
        background_context: dict | None = None,
    ) -> ContentAnalysis:
        payload = {
            "post_text": post_text,
            "publisher_profile": profile.model_dump(),
            "shared_background": background_context or {},
        }
        candidate = self.gateway.invoke_structured(
            stage="content_analysis",
            schema=ContentAnalysis,
            payload=payload,
            system_prompt=(
                "你是发布前沟通风险分析Agent。只分析沟通方式，不判断事实或观点对错。"
                "提取核心表达、限定条件、模糊词、缺失信息、易被截取句、人设冲突和潜在误解。"
                "ambiguous_phrases只能列出原帖中真实出现的短语，text必须是post_text的短子串，"
                "reason必须是普通用户能理解的具体原因；不得把核心表达、内容类型、语气、"
                "缺失信息、潜在误解、shared_background或其他字段名写入ambiguous_phrases。"
                "同时识别内容类型、语气、文本明确信息、合理分歧和无依据推断，并放入各自字段。"
                "shared_background是所有相关Agent和受众共同知晓的联网核对背景；结合它理解事件指代，"
                "但不要把帖子未写出的背景计入explicit_information，也不要据此判断观点对错。"
                "status为uncertain或列在uncertainties中的内容不能当成既定事实。"
                "四类风险使用1到5整数，输出必须符合给定结构。"
            ),
            fallback=lambda: self._demo_analysis(post_text, profile),
        )
        return self._sanitize_analysis(candidate, post_text, profile)

    @staticmethod
    def _sanitize_analysis(
        analysis: ContentAnalysis, post_text: str, profile: PublisherProfile
    ) -> ContentAnalysis:
        fallback = ContentAnalysisChain._demo_analysis(post_text, profile)
        ambiguous = _clean_phrase_issues(analysis.ambiguous_phrases, post_text)
        emotional = _clean_phrase_issues(analysis.emotional_phrases, post_text)
        quotable = _clean_phrase_issues(analysis.quotable_phrases, post_text)
        persona_conflicts = _clean_phrase_issues(analysis.persona_conflicts, post_text)
        if analysis.ambiguous_phrases and not ambiguous:
            ambiguous = fallback.ambiguous_phrases
        return analysis.model_copy(
            update={
                "ambiguous_phrases": ambiguous,
                "emotional_phrases": emotional,
                "quotable_phrases": quotable,
                "persona_conflicts": persona_conflicts,
            }
        )

    @staticmethod
    def _demo_analysis(post_text: str, profile: PublisherProfile) -> ContentAnalysis:
        ambiguous = [
            PhraseIssue(text=phrase, reason=reason)
            for phrase, reason in AMBIGUOUS_RULES.items()
            if phrase in post_text
        ]
        emotional = [
            PhraseIssue(text=phrase, reason=reason)
            for phrase, reason in EMOTIONAL_RULES.items()
            if phrase in post_text
        ]
        quotable = [
            PhraseIssue(text=issue.text, reason="脱离上下文后容易形成更绝对的解读")
            for issue in ambiguous[:2]
        ]
        missing: list[str] = []
        possible: list[str] = []
        audience_conflicts: list[str] = []
        if "减少更新" in post_text or "降低更新" in post_text:
            missing = ["调整后的具体频率", "预计持续时间", "调整原因"]
            possible = ["创作者准备停更", "账号运营或数据出现问题"]
            audience_conflicts = ["长期关注者需要稳定预期", "普通关注者希望知道具体安排"]
        elif "有些人" in post_text or "指手画脚" in post_text:
            missing = ["具体针对的行为", "事件背景", "意见边界"]
            possible = ["发布者在攻击所有不同意见者", "某个未点名群体被公开针对"]
            audience_conflicts = ["支持者可能替发布者扩大指责范围", "路人可能对号入座"]
        elif "处理得不够好" in post_text or "不要只看结果" in post_text:
            missing = ["承担的具体责任", "后续补救措施", "可公开说明的关键背景"]
            possible = ["发布者用复杂情况为结果辩解", "道歉只是为了平息争议"]
            audience_conflicts = ["受影响者关注责任与补救", "老粉更愿意接受背景解释"]
        else:
            if ambiguous:
                missing = ["模糊表达对应的具体范围"]
                possible = ["受众根据自身立场补全未说明的信息"]
            audience_conflicts = ["不同熟悉程度的受众可能采用不同解释"]

        ambiguity_load = min(3, len(ambiguous))
        emotion_load = min(3, len(emotional))
        misunderstanding = min(5, 1 + ambiguity_load + (1 if missing else 0))
        negative = min(5, 1 + emotion_load + (1 if "不要" in post_text else 0))
        conflict = min(5, 1 + emotion_load + (1 if "有些人" in post_text else 0))
        off_topic = min(5, 1 + len(quotable) + (1 if "有些人" in post_text else 0))
        persona_conflicts = []
        if emotional and any(word in profile.style for word in ("理性", "亲切", "坦诚")):
            persona_conflicts.append(
                PhraseIssue(text=emotional[0].text, reason=f"与发布者自述的“{profile.style}”风格存在张力")
            )
        if any(word in post_text for word in ("我觉得", "我认为", "更喜欢")):
            content_type = "个人观点"
            disagreements = ["受众可以有不同偏好或经验"]
        elif any(word in post_text for word in ("将会", "准备", "宣布", "更新")):
            content_type = "通知或安排"
            disagreements = ["受众可能对安排的影响有不同感受"]
        elif any(word in post_text for word in ("对不起", "抱歉", "责任")):
            content_type = "道歉或回应"
            disagreements = ["受众对责任和补救是否充分可能有分歧"]
        elif any(word in post_text for word in ("推荐", "好用", "值得", "购买")):
            content_type = "推荐或评价"
            disagreements = ["不同使用经验可能导致不同评价"]
        else:
            content_type = "经历或日常表达"
            disagreements = ["受众可能从不同生活经验出发理解"]
        tone = "强烈" if emotional else "平静"
        unsupported = (
            ["将个人表达扩大成对所有人的要求"]
            if content_type == "个人观点" else []
        )
        return ContentAnalysis(
            main_message=post_text.strip("。！？")[:100],
            content_type=content_type,
            tone=tone,
            main_viewpoints=[post_text.strip()],
            explicit_information=[post_text.strip()],
            reasonable_disagreements=disagreements,
            unsupported_inferences=unsupported,
            involved_groups=["发布者现有受众", "不了解背景的普通路人"],
            qualifiers=[word for word in ("最近", "适当", "当时", "有些") if word in post_text],
            ambiguous_phrases=ambiguous,
            missing_information=missing,
            emotional_phrases=emotional,
            quotable_phrases=quotable,
            persona_conflicts=persona_conflicts,
            audience_conflicts=audience_conflicts,
            possible_misreadings=possible,
            risk_scores=RiskScores(
                misunderstanding_risk=misunderstanding,
                negative_emotion_risk=negative,
                conflict_risk=conflict,
                off_topic_risk=off_topic,
            ),
        )
