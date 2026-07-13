from __future__ import annotations

from chains.comment_chain import CommentChain
from models.schemas import BackgroundClaim, CommentBatch, WebResearchResult
from services.orchestrator import CommentLabOrchestrator


class CapturingGateway:
    def __init__(self) -> None:
        self.payload = None

    def invoke_structured(self, *, payload, fallback, **kwargs):
        self.payload = payload
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

    context = CommentLabOrchestrator._comment_background(research)

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
    assert CommentLabOrchestrator._comment_background(research) is None


def test_every_round_payload_receives_the_same_background(orchestrator, profile) -> None:
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
