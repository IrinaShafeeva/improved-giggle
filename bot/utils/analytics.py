"""Lightweight analytics — log events to DB."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Event

logger = logging.getLogger(__name__)


async def log_event(
    session: AsyncSession,
    event_type: str,
    user_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    event = Event(
        user_id=user_id,
        event_type=event_type,
        metadata_json=metadata,
    )
    session.add(event)
    await session.commit()
    logger.debug("Event logged: %s user=%s", event_type, user_id)
