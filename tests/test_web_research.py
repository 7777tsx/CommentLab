from __future__ import annotations

import json

from config import Settings
from models.schemas import WebResearchResult, WebSource
from services.web_research import WebResearchService


def test_web_research_is_unavailable_in_demo_mode(tmp_path) -> None:
    settings = Settings(
        demo_mode=True,
        web_search_enabled=True,
        database_path=tmp_path / "test.db",
    )
    result = WebResearchService(settings).run("测试帖子", "测试事件")
    assert result.status == "unavailable"
    assert result.sources == []


def test_structured_claims_bind_only_to_returned_sources() -> None:
    sources = [
        WebSource(
            title="官方来源",
            url="https://example.com/official",
            domain="example.com",
        )
    ]
    raw = json.dumps(
        {
            "event_name": "测试事件",
            "conclusion": "核心信息已经得到公开来源支持。",
            "claims": [
                {
                    "text": "官方已经发布公告",
                    "status": "confirmed",
                    "source_urls": ["https://example.com/official"],
                },
                {
                    "text": "另一说法尚无依据",
                    "status": "confirmed",
                    "source_urls": ["https://unknown.example/item"],
                },
            ],
            "uncertainties": ["具体执行范围仍需确认"],
        },
        ensure_ascii=False,
    )
    result = WebResearchService._parse_research_payload(raw, sources, "测试")
    assert result.event_name == "测试事件"
    assert result.conclusion == "核心信息已经得到公开来源支持。"
    assert result.claims[0].status == "confirmed"
    assert result.claims[0].source_indexes == [0]
    assert result.claims[1].status == "uncertain"
    assert result.claims[1].source_indexes == []
    assert len(result.uncertainties) == 1


def test_non_json_result_has_concise_compatible_fallback() -> None:
    result = WebResearchService._parse_research_payload("背景说明 " * 100, [])
    assert result.status == "completed"
    assert 1 <= len(result.conclusion) <= 100
    assert result.summary == result.conclusion
    assert result.uncertainties


def test_web_research_extracts_and_deduplicates_sources() -> None:
    output = [
        {
            "type": "web_search_call",
            "action": {
                "sources": [
                    {"url": "https://example.com/a", "title": "来源A"},
                    {"url": "https://example.com/a/", "title": "重复来源"},
                ]
            },
        },
        {
            "type": "message",
            "content": [
                {
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://example.org/b",
                            "title": "来源B",
                        }
                    ]
                }
            ],
        },
    ]
    sources = WebResearchService._extract_sources(output)
    assert [(item.title, item.url, item.domain) for item in sources] == [
        ("来源A", "https://example.com/a", "example.com"),
        ("来源B", "https://example.org/b", "example.org"),
    ]


def test_old_saved_result_remains_loadable() -> None:
    result = WebResearchResult.model_validate(
        {
            "status": "completed",
            "event_hint": "旧事件",
            "summary": "旧版摘要",
            "sources": [
                {
                    "title": "旧来源",
                    "url": "https://example.com/old",
                }
            ],
        }
    )
    assert result.conclusion == ""
    assert result.summary == "旧版摘要"
    assert result.sources[0].domain == ""
