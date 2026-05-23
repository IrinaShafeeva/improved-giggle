"""Admin-only maintenance commands."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.models import User

logger = logging.getLogger(__name__)
router = Router()


THE_DAY_UPDATE_TEXT = """Обновление theday: теперь это «Мой день».

Что изменилось:

🧠 Выгрузка
Можно отправить голосовое или текст. Бот отражает, что слышит: чувства, структуру мыслей, незаметные установки/риски и задачи.

📌 Контекст
Появился контекст недели и контекст месяца. Туда можно записать, что сейчас происходит в жизни, чем вы занимаетесь, какие проекты, ограничения и фокус важно учитывать.
В понедельник бот напомнит обновить контекст недели.
В первый день месяца бот напомнит обновить контекст месяца.

📋 Задачи
Бот сам вытаскивает задачи из утренней выгрузки и предлагает добавить их в список на сегодня.
В списке задач можно отметить сделанное, перенести на завтра или добавить новую задачу кнопкой «➕ Добавить задачу».

⚙️ Настройки
Добавлен режим тона «Без терапии»: без коучинговой воды, без морализаторства и без фраз вроде «вы слишком много на себя берете». Только отражение, структура, контекст и действия.

Кнопки теперь такие:
🧠 Выгрузка
📌 Контекст
📋 Задачи
⚙️ Настройки"""


def _admin_ids() -> set[int]:
    ids: set[int] = set()
    for raw in settings.admin_tg_ids.split(","):
        raw = raw.strip()
        if raw.isdigit():
            ids.add(int(raw))
    return ids


def _is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in _admin_ids())


@router.message(Command("broadcast_update"))
async def broadcast_update(
    message: Message,
    bot: Bot,
    db: AsyncSession,
) -> None:
    """Preview or send the current release note to all known bot users."""
    if not _is_admin(message):
        await message.answer("Команда доступна только администратору.")
        return

    text = message.text or ""
    if "confirm" not in text.split()[1:]:
        await message.answer(
            "Превью рассылки:\n\n"
            f"{THE_DAY_UPDATE_TEXT}\n\n"
            "Чтобы отправить всем пользователям из базы, напиши:\n"
            "/broadcast_update confirm",
            parse_mode=None,
        )
        return

    result = await db.execute(select(User).where(User.tg_id.isnot(None)))
    users = result.scalars().all()

    sent = 0
    failed = 0
    await message.answer(f"Начинаю рассылку для {len(users)} пользователей...", parse_mode=None)

    for user in users:
        try:
            await bot.send_message(
                chat_id=user.tg_id,
                text=THE_DAY_UPDATE_TEXT,
                parse_mode=None,
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as exc:
            failed += 1
            logger.warning("Failed to send update broadcast to %s: %s", user.tg_id, exc)

    await message.answer(
        f"Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}",
        parse_mode=None,
    )
