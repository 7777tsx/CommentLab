from __future__ import annotations

from chains.audience_chain import AudienceChain
from chains.content_analysis_chain import ContentAnalysisChain
from models.schemas import (
    AudiencePlan,
    ContentAnalysis,
    PreparationDraft,
    PublisherProfile,
)
from services.llm_client import ModelGateway


class PreparationChain:
    """Generate content analysis and the initial audience plan in one model call."""

    def __init__(
        self,
        gateway: ModelGateway,
        content_chain: ContentAnalysisChain,
        audience_chain: AudienceChain,
    ):
        self.gateway = gateway
        self.content_chain = content_chain
        self.audience_chain = audience_chain

    def run(
        self,
        post_text: str,
        profile: PublisherProfile,
        *,
        background_context: dict | None = None,
    ) -> tuple[ContentAnalysis, AudiencePlan]:
        payload = {
            "post_text": post_text,
            "publisher_profile": profile.model_dump(),
            "shared_background": background_context or {},
            "allowed_personas": [
                {
                    "persona_id": item.persona_id,
                    "label": item.label,
                    "group_name": item.group_name,
                    "description": item.description,
                }
                for item in self.audience_chain.templates
            ],
        }
        candidate = self.gateway.invoke_structured(
            stage="preparation",
            schema=PreparationDraft,
            payload=payload,
            system_prompt=(
                "你是发布前分析与受众规划Agent。一次完成两个相互一致的结果。"
                "analysis只分析沟通方式，不判断事实或观点对错；提取核心表达、限定条件、"
                "模糊词、缺失信息、易被截取句、人设冲突、合理分歧、无依据推断和潜在误解。"
                "所有PhraseIssue.text必须逐字复制post_text中的连续短语，不得输出字段名。"
                "四类文本风险先按1到5整数填写，系统会根据可见证据重新计算。"
                "audience只能使用allowed_personas中的模板和persona_id，不得发明真实用户；"
                "结合analysis和发布者画像设置初始权重及大类比例，潜水点赞者必须active=false。"
                "该方案只是可编辑初稿，用户确认后的比例会覆盖它。"
                "shared_background供两个部分共同理解事件指代，但帖子未写出的背景不得计入"
                "explicit_information，不确定信息不得当成既定事实。输出必须符合给定结构。"
            ),
            fallback=lambda: PreparationDraft(
                analysis=self.content_chain._demo_analysis(post_text, profile),
                audience=self.audience_chain._default_plan(),
            ),
        )
        analysis = self.content_chain._sanitize_analysis(
            candidate.analysis, post_text, profile
        )
        audience = self.audience_chain._sanitize_plan(candidate.audience)
        return analysis, audience
