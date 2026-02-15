"""Voice message transcription via Whisper-compatible API."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from openai import AsyncOpenAI

from bot.config import settings

logger = logging.getLogger(__name__)


class BaseTranscriber(ABC):
    @abstractmethod
    async def transcribe(self, file_path: str | Path) -> str:
        ...


class WhisperTranscriber(BaseTranscriber):
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.whisper_api_key,
            base_url=settings.whisper_base_url,
        )
        self._model = settings.whisper_model

    async def transcribe(self, file_path: str | Path) -> str:
        file_path = Path(file_path)
        logger.info("Transcribing %s", file_path.name)
        with open(file_path, "rb") as f:
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=f,
                language="ru",
            )
        return response.text


# Singleton
transcriber: BaseTranscriber = WhisperTranscriber()
