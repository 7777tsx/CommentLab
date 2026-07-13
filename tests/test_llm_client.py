from __future__ import annotations

from config import Settings
from models.schemas import RewriteResult
from services.database import Database
from services.llm_client import ModelGateway, parse_structured_json


def test_structured_json_repairs_code_fence_and_trailing_comma() -> None:
    raw = '''```json
    {
      "rewritten_post": "这是一条完成修订后的测试文本。",
      "preserved_elements": ["核心观点"],
      "repaired_risks": ["指代不清"],
      "explanation": "保留原意并明确范围",
    }
    ```'''
    result = parse_structured_json(RewriteResult, raw)
    assert result.rewritten_post.startswith("这是一条")


def test_missing_credentials_select_demo_mode(orchestrator) -> None:
    assert orchestrator.demo_mode is True


def test_live_gateway_repairs_raw_invalid_json_and_caches(tmp_path) -> None:
    raw_json = '''```json
    {
      "rewritten_post": "这是一条经过结构化修复的测试文本。",
      "preserved_elements": ["核心观点"],
      "repaired_risks": ["信息不清"],
      "explanation": "修复尾随逗号",
    }
    ```'''

    class Raw:
        content = raw_json

    class Structured:
        calls = 0

        def invoke(self, messages):
            self.calls += 1
            return {"parsed": None, "raw": Raw(), "parsing_error": ValueError("bad json")}

    class FakeModel:
        def __init__(self):
            self.structured = Structured()

        def with_structured_output(self, schema, include_raw=False):
            assert include_raw is True
            return self.structured

    settings = Settings(
        api_key="test",
        base_url="https://example.invalid/v1",
        model="test-model",
        demo_mode=False,
        database_path=tmp_path / "cache.db",
    )
    gateway = ModelGateway(settings, Database(settings.database_path))
    fake = FakeModel()
    gateway._model = fake
    kwargs = dict(
        stage="rewrite",
        schema=RewriteResult,
        payload={"post": "test"},
        system_prompt="test",
        fallback=lambda: (_ for _ in ()).throw(AssertionError("fallback used")),
    )
    first = gateway.invoke_structured(**kwargs)
    second = gateway.invoke_structured(**kwargs)
    assert first == second
    assert fake.structured.calls == 1
