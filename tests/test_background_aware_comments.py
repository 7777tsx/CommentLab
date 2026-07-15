from __future__ import annotations

from chains.comment_chain import CommentChain
from models.schemas import BackgroundClaim, CommentBatch, WebResearchResult
from services.orchestrator import CommentLabOrchestrator


class CapturingGateway:
    def __init__(self) -> None:
        self.payload = None
        self.calls = []

    def invoke_structured(self, *, stage, payload, fallback, **kwargs):
        self.payload = payload
        self.calls.append((stage, payload))
        return fallback()


def test_completed_research_becomes_concise_shared_fact_card() -> None:
    research = WebResearchResult(
        status="completed",
        event_name="示例事件",
        conclusion="已确认事件发生。",
        claims=[
            BackgroundClaim(text="事实一", status="confirmed"),
            BackgroundClaim(text="当事方已作回应", status="party_statement"),
        ],
        uncertainties=["具体时间仍待确认", "这条不应进入事实卡"],
    )

    context = CommentLabOrchestrator._shared_background(research)

    assert context == {
        "event_name": "示例事件",
        "conclusion": "已确认事件发生。",
        "claims": [
            {"text": "事实一", "status": "confirmed"},
            {"text": "当事方已作回应", "status": "party_statement"},
        ],
        "uncertainties": ["具体时间仍待确认"],
    }


def test_failed_research_is_not_injected() -> None:
    research = WebResearchResult(status="failed", summary="搜索失败")
    assert CommentLabOrchestrator._shared_background(research) is None


def test_comment_payload_receives_the_shared_background(orchestrator, profile) -> None:
    gateway = CapturingGateway()
    chain = CommentChain(gateway)
    persona = orchestrator.audience_chain._default_plan().personas[0]
    background = {
        "event_name": "示例事件",
        "conclusion": "结论很简短",
        "claims": [{"text": "事实一", "status": "confirmed"}],
        "uncertainties": [],
    }

    result = chain.run_round(
        post_text="这是用于测试背景注入的一条帖子文本。",
        profile=profile,
        personas=[persona],
        visible_comments=[],
        round_no=1,
        version="before",
        background_context=background,
    )

    assert isinstance(result, CommentBatch)
    assert gateway.payload["shared_background"] == background


def test_all_agents_receive_the_same_validated_background(
    monkeypatch, orchestrator, profile
) -> None:
    research = WebResearchResult(
        status="completed",
        event_name="示例事件",
        conclusion="公开来源确认了核心事件。",
        claims=[
            BackgroundClaim(
                text="官方已经发布公告",
                status="confirmed",
                source_indexes=[0],
            )
        ],
        uncertainties=["部分细节仍待确认"],
    )
    monkeypatch.setattr(
        orchestrator.web_research,
        "run",
        lambda post_text, event_hint="": research,
    )
    gateway = CapturingGateway()
    for chain in (
        orchestrator.content_chain,
        orchestrator.audience_chain,
        orchestrator.comment_chain,
        orchestrator.risk_chain,
        orchestrator.rewrite_chain,
        orchestrator.comparison_chain,
    ):
        chain.gateway = gateway

    prepared = orchestrator.prepare(
        "有些人真的应该学会尊重别人，不要什么事情都来指手画脚。",
        profile,
        search_background=True,
        event_hint="示例事件",
    )
    orchestrator.complete(prepared, seed=17)

    expected = CommentLabOrchestrator._shared_background(research)
    required_stages = {
        "content_analysis",
        "audience_plan",
        "risk_before",
        "rewrite",
        "risk_after",
        "comparison",
    }
    called_stages = {stage for stage, _payload in gateway.calls}
    assert required_stages <= called_stages
    assert len(
        [stage for stage, _payload in gateway.calls if stage.startswith("comment_round_")]
    ) == 6
    assert all(payload["shared_background"] == expected for _stage, payload in gateway.calls)
