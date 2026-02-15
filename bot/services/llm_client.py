"""LLM client abstraction – OpenAI-compatible API behind an interface."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from openai import AsyncOpenAI

from bot.config import settings

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """Interface so providers can be swapped."""

    @abstractmethod
    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        ...

    @abstractmethod
    async def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        ...


class OpenAICompatibleClient(BaseLLMClient):
    """Works with any OpenAI-compatible API (OpenAI, Together, Groq, etc.)."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        self._model = settings.llm_model

    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.error("LLM returned invalid JSON: %s", raw[:500])
            return {"error": "invalid_json", "raw": raw[:500]}


# Singleton
llm_client: BaseLLMClient = OpenAICompatibleClient()
