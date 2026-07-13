from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from config import Settings
from models.schemas import WebResearchResult, WebSource


RESEARCH_INSTRUCTIONS = """
你是发布前沟通风险系统中的事件背景研究Agent。
你的任务是使用联网搜索，简要说明帖子可能指代的公开事件背景。

必须遵守：
1. 不判断发布者观点对错，不把猜测写成事实。
2. 如果帖子无法唯一对应某个事件，明确说明指代存在歧义。
3. 区分已公开确认的信息、当事方说法、争议说法和仍未知的信息。
4. 优先使用事件当事方公开材料、正式机构和有编辑审核的新闻来源。
5. 不搜索或推断普通个人的住址、电话等敏感信息。
6. 用中文输出，控制在300字以内。
7. 输出只包含：可能指代的事件、简要背景、仍存在的不确定性。
"""


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


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
            "请先判断是否存在可检索的公开事件指代；如有则搜索并给出简要背景。"
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
            summary = str(getattr(response, "output_text", "") or "").strip()
            if not summary:
                summary = "模型未返回可显示的事件背景摘要。"
            sources = self._extract_sources(getattr(response, "output", []))
            self.last_error = None
            return WebResearchResult(
                status="completed",
                event_hint=hint,
                summary=summary[:1200],
                sources=sources[:8],
            )
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
    def _extract_sources(output: Any) -> list[WebSource]:
        found: list[WebSource] = []
        seen: set[str] = set()

        def add(url: str | None, title: str | None = None) -> None:
            if not url or not url.startswith(("http://", "https://")) or url in seen:
                return
            seen.add(url)
            host = urlparse(url).netloc
            found.append(WebSource(title=(title or host or url)[:200], url=url))

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
