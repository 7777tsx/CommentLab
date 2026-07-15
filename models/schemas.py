from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RiskLevel = Literal["低", "中", "高"]
Stance = Literal["support", "oppose", "question", "neutral"]
ActionType = Literal["comment", "reply", "like", "ignore"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublisherProfile(StrictModel):
    identity: str = Field(min_length=1, max_length=50)
    domain: str = Field(min_length=1, max_length=80)
    follower_scale: str = Field(min_length=1, max_length=30)
    style: str = Field(min_length=1, max_length=100)
    audience_relationship: str = Field(min_length=1, max_length=120)


class PhraseIssue(StrictModel):
    text: str
    reason: str


class RiskScores(StrictModel):
    misunderstanding_risk: int = Field(ge=1, le=5)
    negative_emotion_risk: int = Field(ge=1, le=5)
    conflict_risk: int = Field(ge=1, le=5)
    off_topic_risk: int = Field(ge=1, le=5)

    def weighted_score(self) -> float:
        return round(
            self.misunderstanding_risk * 0.40
            + self.negative_emotion_risk * 0.30
            + self.conflict_risk * 0.20
            + self.off_topic_risk * 0.10,
            3,
        )


class ContentAnalysis(StrictModel):
    main_message: str
    content_type: str = "其他"
    tone: str = "中性"
    main_viewpoints: list[str] = Field(default_factory=list)
    explicit_information: list[str] = Field(default_factory=list)
    reasonable_disagreements: list[str] = Field(default_factory=list)
    unsupported_inferences: list[str] = Field(default_factory=list)
    involved_groups: list[str] = Field(default_factory=list)
    qualifiers: list[str] = Field(default_factory=list)
    ambiguous_phrases: list[PhraseIssue] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    emotional_phrases: list[PhraseIssue] = Field(default_factory=list)
    quotable_phrases: list[PhraseIssue] = Field(default_factory=list)
    persona_conflicts: list[PhraseIssue] = Field(default_factory=list)
    audience_conflicts: list[str] = Field(default_factory=list)
    possible_misreadings: list[str] = Field(default_factory=list)
    risk_scores: RiskScores

    @property
    def text_analysis_score(self) -> float:
        return self.risk_scores.weighted_score()


class PersonaSpec(StrictModel):
    persona_id: str
    label: str
    group_name: str
    description: str
    weight: float = Field(default=1.0, ge=0, le=10)
    reading_depth: float = Field(default=0.7, ge=0, le=1)
    trust: float = Field(default=0.5, ge=0, le=1)
    emotion_sensitivity: float = Field(default=0.5, ge=0, le=1)
    controversy_tendency: float = Field(default=0.3, ge=0, le=1)
    influence: float = Field(default=0.5, ge=0, le=1)
    active: bool = True


class AudiencePlan(StrictModel):
    personas: list[PersonaSpec]
    group_ratios: dict[str, float]
    rationale: str

    @field_validator("group_ratios")
    @classmethod
    def ratios_must_be_non_negative(cls, value: dict[str, float]) -> dict[str, float]:
        if any(v < 0 for v in value.values()):
            raise ValueError("受众比例不能为负数")
        return value

    def normalized(self) -> "AudiencePlan":
        ratios = normalize_ratios(self.group_ratios)
        personas = [p.model_copy(deep=True) for p in self.personas]
        group_totals: dict[str, float] = {}
        for persona in personas:
            group_totals[persona.group_name] = group_totals.get(persona.group_name, 0.0) + persona.weight
        for persona in personas:
            group_total = group_totals.get(persona.group_name, 0.0)
            group_ratio = ratios.get(persona.group_name, 0.0)
            persona.weight = 0.0 if group_total == 0 else group_ratio * persona.weight / group_total
        return AudiencePlan(personas=personas, group_ratios=ratios, rationale=self.rationale)


def normalize_ratios(ratios: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in ratios.values())
    if total <= 0:
        if not ratios:
            return {}
        equal = 1.0 / len(ratios)
        return {key: equal for key in ratios}
    return {key: max(0.0, value) / total for key, value in ratios.items()}


class CommentAction(StrictModel):
    persona_id: str
    action: ActionType
    target_comment_id: str | None = None
    text: str | None = None
    stance: Stance = "neutral"
    emotion: str = "平静"
    emotion_intensity: float = Field(default=0.2, ge=0, le=1)
    controversy: float = Field(default=0.2, ge=0, le=1)
    misunderstanding: bool = False
    off_topic: bool = False
    evidence_span: str = ""
    reaction_type: str = "opinion"

    @model_validator(mode="after")
    def action_has_valid_shape(self) -> "CommentAction":
        if self.action in {"comment", "reply"}:
            if not self.text:
                raise ValueError("评论或回复必须包含文本")
            if not 10 <= len(self.text) <= 60:
                raise ValueError("评论文本必须为10至60个字符")
        if self.action == "reply" and not self.target_comment_id:
            raise ValueError("回复必须指定目标评论")
        return self


class CommentBatch(StrictModel):
    actions: list[CommentAction]


class Comment(StrictModel):
    comment_id: str
    persona_id: str
    persona_label: str
    parent_id: str | None = None
    round_no: int = Field(ge=1, le=3)
    text: str = Field(min_length=10, max_length=60)
    stance: Stance
    emotion: str
    emotion_intensity: float = Field(ge=0, le=1)
    controversy: float = Field(ge=0, le=1)
    likes: int = Field(default=0, ge=0)
    reply_count: int = Field(default=0, ge=0)
    hot_score: float = Field(default=0, ge=0)
    misunderstanding: bool = False
    off_topic: bool = False
    evidence_span: str = ""
    reaction_type: str = "opinion"


class TraceEvent(StrictModel):
    round_no: int
    event_type: str
    detail: str


class SimulationConfig(StrictModel):
    post_text: str = Field(min_length=1, max_length=500)
    version: Literal["before", "after"] = "before"
    seed: int = 42
    lurker_count: int = Field(default=50, ge=0, le=500)
    rounds: int = Field(default=3, ge=1, le=3)
    activation_counts: list[int] = Field(default_factory=lambda: [7, 4, 3])

    @field_validator("post_text")
    @classmethod
    def post_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("帖子不能为空")
        return value

    @model_validator(mode="after")
    def activation_matches_rounds(self) -> "SimulationConfig":
        if len(self.activation_counts) < self.rounds:
            raise ValueError("每轮激活人数配置不足")
        return self


class SimulationMetrics(StrictModel):
    misunderstanding_ratio: float = Field(ge=0, le=1)
    negative_ratio: float = Field(ge=0, le=1)
    conflict_reply_count: int = Field(ge=0)
    off_topic_ratio: float = Field(ge=0, le=1)


class SimulationResult(StrictModel):
    config: SimulationConfig
    audience: AudiencePlan
    comments: list[Comment]
    metrics: SimulationMetrics
    trace: list[TraceEvent]


class RiskySpan(StrictModel):
    text: str
    reason: str


class MisunderstandingChain(StrictModel):
    source_span: str = Field(default="", max_length=200)
    steps: list[str] = Field(min_length=1, max_length=6)


class RiskReport(StrictModel):
    overall_level: RiskLevel
    risk_scores: RiskScores
    text_analysis_score: float = Field(ge=1, le=5)
    simulation_score: float = Field(ge=1, le=5)
    final_score: float = Field(ge=1, le=5)
    risky_spans: list[RiskySpan]
    misunderstanding_chains: list[MisunderstandingChain]
    modification_directions: list[str]
    summary: str

    @field_validator("misunderstanding_chains", mode="before")
    @classmethod
    def migrate_legacy_misunderstanding_chains(cls, value):
        """Accept historical string chains while new results use anchored objects."""
        if not isinstance(value, list):
            return value
        migrated = []
        for item in value:
            if not isinstance(item, str):
                migrated.append(item)
                continue
            nodes = [
                node.strip()
                for node in re.split(r"\s*(?:→|⇒|➡|->|=>|—>)\s*", item)
                if node.strip()
            ]
            if not nodes:
                continue
            source_span = ""
            quoted = re.match(r'^[“\"](.+?)[”\"](.*)$', nodes[0])
            if quoted:
                source_span = quoted.group(1).strip()
                remainder = quoted.group(2).strip()
                nodes = ([remainder] if remainder else []) + nodes[1:]
            migrated.append(
                {
                    "source_span": source_span,
                    "steps": nodes or ["受众产生不同理解"],
                }
            )
        return migrated


class RewriteResult(StrictModel):
    rewritten_post: str = Field(min_length=1, max_length=500)
    preserved_elements: list[str]
    repaired_risks: list[str]
    explanation: str


class ComparisonReport(StrictModel):
    risk_before: RiskLevel
    risk_after: RiskLevel
    misunderstanding_change: float
    negative_change: float
    conflict_change: int
    off_topic_change: float
    resolved_misreadings: list[str]
    remaining_questions: list[str]
    persona_consistency: bool
    conclusion: str


class WebSource(StrictModel):
    title: str
    url: str
    domain: str = ""
    published_at: str | None = None
    excerpt: str = ""


class BackgroundClaim(StrictModel):
    text: str = Field(min_length=1, max_length=100)
    status: Literal["confirmed", "party_statement", "disputed", "uncertain"]
    source_indexes: list[int] = Field(default_factory=list)


class WebResearchResult(StrictModel):
    status: Literal["completed", "skipped", "unavailable", "failed"]
    event_hint: str = ""
    event_name: str = ""
    conclusion: str = ""
    claims: list[BackgroundClaim] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    summary: str = ""
    sources: list[WebSource] = Field(default_factory=list)
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"


class PreparedProject(StrictModel):
    project_id: str = Field(default_factory=lambda: uuid4().hex)
    post_text: str
    publisher_profile: PublisherProfile
    analysis: ContentAnalysis
    audience: AudiencePlan
    background_research: WebResearchResult | None = None


class ProjectResult(StrictModel):
    project_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    post_text: str
    publisher_profile: PublisherProfile
    analysis_before: ContentAnalysis
    audience: AudiencePlan
    simulation_before: SimulationResult
    risk_before: RiskReport
    rewrite: RewriteResult
    analysis_after: ContentAnalysis
    simulation_after: SimulationResult
    risk_after: RiskReport
    comparison: ComparisonReport
    background_research: WebResearchResult | None = None


class HistoryItem(StrictModel):
    project_id: str
    created_at: str
    post_text: str
    overall_risk_before: str
    overall_risk_after: str


def model_json(value: BaseModel | dict[str, Any]) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    import json

    return json.dumps(value, ensure_ascii=False)
