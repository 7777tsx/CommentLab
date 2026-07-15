from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from config import Settings
from models.schemas import BackgroundClaim, WebResearchResult, WebSource


RESEARCH_INSTRUCTIONS = """
你是发布前沟通风险系统中的事件核对Agent。
发布者通常已经了解事件背景，因此不要写科普长文，只核对最关键的信息。

必须遵守：
1. 使用联网搜索核对帖子可能指代的公开事件。
2. 不判断发布者观点对错，不把猜测写成事实。
3. 指代不唯一时直接说明歧义，不强行匹配。
4. 优先使用当事方公开材料、正式机构和有编辑审核的新闻来源。
5. 不搜索或推断普通个人的住址、电话等敏感信息。
6. 总内容尽可能简短：一句结论，最多3条关键事实，最多1条不确定性。
7. 只输出JSON，不使用Markdown或代码围栏。

JSON结构：
{
  "event_name": "事件简称，不超过30字",
  "conclusion": "给知情发布者的一句话核对结论，不超过60字",
  "claims": [
    {
      "text": "关键事实，不超过50字",
      "status": "confirmed|party_statement|disputed|uncertain",
      "source_urls": ["必须是本次搜索实际返回的完整URL"]
    }
  ],
  "uncertainties": ["仍需注意的不确定性，不超过50字"]
}
"""


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _clean_url(url: str) -> str:
    return url.strip().rstrip("/")


class WebResearchService:
    """Optional Responses API web-search path, isolated from the existing chains."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_error: str | None = None
        self._client = None

    @property
    def available(self) -> bool:
        return self.settings.web_search_enabled and self.settings.live_ready

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.settings.timeout,
                max_retries=1,
            )
        return self._client

    def run(self, post_text: str, event_hint: str = "") -> WebResearchResult:
        hint = event_hint.strip()[:200]
        if not self.settings.web_search_enabled:
            return WebResearchResult(
                status="skipped",
                event_hint=hint,
                summary="联网搜索已在配置中关闭。",
            )
        if not self.settings.live_ready:
            return WebResearchResult(
                status="unavailable",
                event_hint=hint,
                summary="当前为DEMO_MODE，未调用联网搜索。",
            )

        user_text = (
            f"帖子：\n{post_text}\n\n"
            f"用户补充的事件线索：\n{hint or '无'}\n\n"
            "请联网核对事件，只返回给知情发布者有用的最简结论。"
        )
        try:
            response = self._get_client().responses.create(
                model=self.settings.web_search_model or self.settings.model,
                tools=[
                    {
                        "type": "web_search",
                        "search_context_size": "medium",
                    }
                ],
                input=[
                    {"role": "system", "content": RESEARCH_INSTRUCTIONS},
                    {"role": "user", "content": user_text},
                ],
            )
            raw_text = str(getattr(response, "output_text", "") or "").strip()
            sources = self._extract_sources(getattr(response, "output", []))
            result = self._parse_research_payload(raw_text, sources, hint)
            self.last_error = None
            return result
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if self.settings.api_key:
                message = message.replace(self.settings.api_key, "***")
            self.last_error = message[:300]
            return WebResearchResult(
                status="failed",
                event_hint=hint,
                summary="当前模型服务未完成联网搜索，原有文本分析和模拟流程不受影响。",
                error_message=self.last_error,
            )

    @staticmethod
    def _parse_research_payload(
        raw_text: str,
        sources: list[WebSource],
        event_hint: str = "",
    ) -> WebResearchResult:
        text = raw_text.strip()
        fence = chr(96) * 3
        if text.startswith(fence):
            lines = text.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == fence:
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return WebResearchResult(
                status="failed",
                event_hint=event_hint,
                summary="联网核对结果未通过结构化校验，未向后续 Agent 注入该内容。",
                error_message="invalid_research_payload",
            )

        if not isinstance(payload, dict):
            return WebResearchResult(
                status="failed",
                event_hint=event_hint,
                summary="联网核对结果结构无效，未向后续 Agent 注入该内容。",
                error_message="invalid_research_payload",
            )

        url_to_index = {
            _clean_url(source.url): index
            for index, source in enumerate(sources[:8])
        }
        claims: list[BackgroundClaim] = []
        allowed_statuses = {
            "confirmed",
            "party_statement",
            "disputed",
            "uncertain",
        }
        for item in payload.get("claims", [])[:3]:
            if not isinstance(item, dict):
                continue
            claim_text = str(item.get("text", "")).strip()[:100]
            if not claim_text:
                continue
            indexes = sorted(
                {
                    url_to_index[_clean_url(str(url))]
                    for url in item.get("source_urls", [])
                    if _clean_url(str(url)) in url_to_index
                }
            )
            status = str(item.get("status", "uncertain"))
            if status not in allowed_statuses:
                status = "uncertain"
            if not indexes and status in {"confirmed", "party_statement"}:
                status = "uncertain"
            claims.append(
                BackgroundClaim(
                    text=claim_text,
                    status=status,
                    source_indexes=indexes,
                )
            )

        event_name = str(payload.get("event_name", "")).strip()[:60]
        conclusion = str(payload.get("conclusion", "")).strip()[:100]
        if not conclusion:
            conclusion = claims[0].text if claims else "未形成明确的事件核对结论。"
        uncertainties = [
            str(item).strip()[:80]
            for item in payload.get("uncertainties", [])[:1]
            if str(item).strip()
        ]
        return WebResearchResult(
            status="completed",
            event_hint=event_hint,
            event_name=event_name,
            conclusion=conclusion,
            claims=claims,
            uncertainties=uncertainties,
            summary=conclusion,
            sources=sources[:8],
        )

    @staticmethod
    def _extract_sources(output: Any) -> list[WebSource]:
        found: list[WebSource] = []
        seen: set[str] = set()

        def add(url: str | None, title: str | None = None) -> None:
            if not url or not url.startswith(("http://", "https://")):
                return
            normalized = _clean_url(url)
            if normalized in seen:
                return
            seen.add(normalized)
            host = urlparse(url).netloc
            found.append(
                WebSource(
                    title=(title or host or url)[:200],
                    url=url,
                    domain=host,
                )
            )

        for item in output or []:
            item_type = _value(item, "type", "")
            if item_type == "web_search_call":
                action = _value(item, "action", {})
                for source in _value(action, "sources", []) or []:
                    add(_value(source, "url"), _value(source, "title"))
            if item_type != "message":
                continue
            for content in _value(item, "content", []) or []:
                for annotation in _value(content, "annotations", []) or []:
                    if _value(annotation, "type") == "url_citation":
                        add(_value(annotation, "url"), _value(annotation, "title"))
        return found
