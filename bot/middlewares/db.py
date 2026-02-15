"""Middleware that injects DB session + ensures User row exists."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy import select

from bot.db.models import User
from bot.db.session import async_session


class DbSessionMiddleware(BaseMiddleware):
    """Injects `db` (AsyncSession) and `user_db` (User) into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session() as session:
            data["db"] = session

            # Resolve telegram user
            tg_user = None
            if isinstance(event, Message) and event.from_user:
                tg_user = event.from_user
            elif isinstance(event, CallbackQuery) and event.from_user:
                tg_user = event.from_user

            if tg_user:
                result = await session.execute(
                    select(User).where(User.tg_id == tg_user.id)
                )
                user_db = result.scalar_one_or_none()
                if user_db is None:
                    user_db = User(
                        tg_id=tg_user.id,
                        first_name=tg_user.first_name or "",
                        username=tg_user.username,
                    )
                    session.add(user_db)
                    await session.commit()
                    await session.refresh(user_db)
                data["user_db"] = user_db
            else:
                data["user_db"] = None

            return await handler(event, data)
