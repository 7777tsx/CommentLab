from __future__ import annotations

import json
from pathlib import Path

from models.schemas import AudiencePlan, ContentAnalysis, PersonaSpec, PublisherProfile
from services.llm_client import ModelGateway


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class AudienceChain:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway
        self.templates = [
            PersonaSpec.model_validate(item)
            for item in json.loads((DATA_DIR / "personas.json").read_text(encoding="utf-8"))
        ]

    def run(
        self,
        post_text: str,
        profile: PublisherProfile,
        analysis: ContentAnalysis,
    ) -> AudiencePlan:
        payload = {
            "post_text": post_text,
            "publisher_profile": profile.model_dump(),
            "content_analysis": {
                "main_message": analysis.main_message,
                "content_type": analysis.content_type,
                "tone": analysis.tone,
                "involved_groups": analysis.involved_groups,
                "possible_misreadings": analysis.possible_misreadings[:3],
            },
            "allowed_personas": [
                {
                    "persona_id": item.persona_id,
                    "label": item.label,
                    "group_name": item.group_name,
                    "description": item.description,
                }
                for item in self.templates
            ],
        }
        candidate = self.gateway.invoke_structured(
            stage="audience_plan",
            schema=AudiencePlan,
            payload=payload,
            system_prompt=(
                "你是受众规划Agent。只能从给定的12种Persona模板中规划受众，不能发明真实用户。"
                "保留persona_id及底层属性，结合发布者画像调整权重和大类比例。"
                "潜水点赞者必须active=false。"
            ),
            fallback=self._default_plan,
        )
        return self._sanitize_plan(candidate)

    def _sanitize_plan(self, candidate: AudiencePlan) -> AudiencePlan:
        proposed = {persona.persona_id: persona for persona in candidate.personas}
        personas = []
        for template in self.templates:
            persona = template.model_copy(deep=True)
            if template.persona_id in proposed:
                persona.weight = proposed[template.persona_id].weight
            personas.append(persona)
        allowed_groups = {persona.group_name for persona in self.templates}
        ratios = {
            group: value
            for group, value in candidate.group_ratios.items()
            if group in allowed_groups
        }
        for group in allowed_groups:
            ratios.setdefault(group, 0.0)
        return AudiencePlan(
            personas=personas,
            group_ratios=ratios,
            rationale=candidate.rationale,
        ).normalized()

    def _default_plan(self) -> AudiencePlan:
        return AudiencePlan(
            personas=[persona.model_copy(deep=True) for persona in self.templates],
            group_ratios={
                "粉丝群体": 0.20,
                "路人群体": 0.20,
                "理性群体": 0.20,
                "怀疑群体": 0.15,
                "情绪群体": 0.10,
                "互动群体": 0.15,
                "沉默群体": 0.00,
            },
            rationale="兼顾熟悉发布者的粉丝、不了解背景的路人、理性追问、怀疑、情绪和互动型受众。",
        ).normalized()
