"""Mini-checkin handler — respond to +3h / +6h checkin notifications."""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, Checkin, DailySession, TodoItem
from bot.keyboards.inline import todo_list_kb
from bot.utils.analytics import log_event

logger = logging.getLogger(__name__)

router = Router()

_STATUS_EMOJI = {
    "done": "✅",
    "progress": "🟡",
    "moved": "⏳",
    "help": "🆘",
}

_STATUS_LABEL = {
    "done": "Сделано",
    "progress": "В процессе",
    "moved": "Перенёс",
    "help": "Нужна помощь",
}


@router.callback_query(F.data.startswith("checkin:"))
async def on_checkin_status(
    callback: CallbackQuery,
    db: AsyncSession,
    user_db: User,
) -> None:
    parts = callback.data.split(":")
    # checkin:session_id:kind:status
    if len(parts) != 4:
        await callback.answer("Ошибка формата", show_alert=True)
        return

    _, session_id_str, kind, status = parts
    session_id = int(session_id_str)

    # Verify session belongs to user
    result = await db.execute(
        select(DailySession).where(
            DailySession.id == session_id,
            DailySession.user_id == user_db.id,
        )
    )
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        await callback.answer("Сессия не найдена", show_alert=True)
        return

    # Check for existing checkin of same kind
    existing = await db.execute(
        select(Checkin).where(
            Checkin.daily_session_id == session_id,
            Checkin.kind == kind,
        )
    )
    checkin = existing.scalar_one_or_none()
    if checkin:
        checkin.status = status
    else:
        checkin = Checkin(
            daily_session_id=session_id,
            kind=kind,
            status=status,
        )
        db.add(checkin)
    await db.commit()

    await log_event(db, "checkin_done", user_id=user_db.id, metadata={
        "session_id": session_id, "kind": kind, "status": status,
    })

    emoji = _STATUS_EMOJI.get(status, "")
    label = _STATUS_LABEL.get(status, status)

    hour_label = "3 часа" if kind == "t3" else "6 часов"

    response = f"{emoji} Чекин ({hour_label}): {label}"

    if status == "done":
        response += "\n\nОтлично! Продолжай в том же духе 💪"
    elif status == "help":
        response += "\n\nПонял. В Phase 1 здесь будет возможность запросить помощь у команды."
    elif status == "moved":
        response += "\n\nОк, бывает. Главное — не забросить совсем."

    await callback.message.edit_text(response)

    # Show pending todos if any
    todos_result = await db.execute(
        select(TodoItem).where(
            TodoItem.user_id == user_db.id,
            TodoItem.session_id == session_id,
            TodoItem.status == "pending",
        )
    )
    todos = list(todos_result.scalars().all())
    if todos:
        lines = ["📋 *Дела на сегодня:*"]
        for t in todos:
            lines.append(f"• {t.text}")
        await callback.message.answer(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=todo_list_kb(todos),
        )

    await callback.answer()
