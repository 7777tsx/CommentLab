from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from config import Settings
from services.database import Database


T = TypeVar("T", bound=BaseModel)


def parse_structured_json(schema: type[T], value: str) -> T:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return schema.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValueError):
        repaired = re.sub(r",\s*([}\]])", r"\1", text)
        return schema.model_validate(json.loads(repaired))


class ModelGateway:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.last_error: str | None = None
        self._model = None

    @property
    def demo_mode(self) -> bool:
        return not self.settings.live_ready

    def _cache_key(self, stage: str, payload: dict, system_prompt: str) -> str:
        prompt_fingerprint = hashlib.sha256(
            system_prompt.encode("utf-8")
        ).hexdigest()
        raw = json.dumps(
            {
                "stage": stage,
                "payload": payload,
                "model": self.settings.model,
                "base_url": self.settings.base_url,
                "temperature": self.settings.temperature,
                "prompt_version": self.settings.prompt_version,
                "prompt_fingerprint": prompt_fingerprint,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_model(self):
        if self._model is None:
            from langchain_openai import ChatOpenAI

            self._model = ChatOpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                model=self.settings.model,
                temperature=self.settings.temperature,
                timeout=self.settings.timeout,
                max_retries=0,
            )
        return self._model

    def invoke_structured(
        self,
        *,
        stage: str,
        schema: type[T],
        payload: dict,
        system_prompt: str,
        fallback: Callable[[], T],
    ) -> T:
        if self.demo_mode:
            return fallback()

        cache_key = self._cache_key(stage, payload, system_prompt)
        cached = self.database.cache_get(cache_key)
        if cached:
            return schema.model_validate_json(cached)

        messages = [
            ("system", system_prompt),
            ("human", json.dumps(payload, ensure_ascii=False)),
        ]
        error: Exception | None = None
        for _ in range(2):
            try:
                structured = self._get_model().with_structured_output(
                    schema, include_raw=True
                )
                response = structured.invoke(messages)
                result = response
                if isinstance(response, dict) and "parsed" in response:
                    result = response.get("parsed")
                    if result is None and response.get("raw") is not None:
                        raw = response["raw"]
                        content = raw.content if hasattr(raw, "content") else str(raw)
                        result = parse_structured_json(schema, content)
                if not isinstance(result, schema):
                    result = schema.model_validate(result)
                self.database.cache_set(cache_key, stage, result.model_dump_json())
                self.last_error = None
                return result
            except Exception as exc:  # The complete flow must survive one failed stage.
                error = exc
        self.last_error = f"{stage}: {type(error).__name__}: {error}"
        return fallback()
