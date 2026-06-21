"""Focus selection after dump analysis + energy confirmation."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, DailySession
from bot.keyboards.inline import energy_kb, go_deeper_kb, main_menu_kb, todo_input_kb
from bot.services.scheduler_service import (
    schedule_checkins,
    schedule_evening_reminders,
    schedule_todo_reminders,
)
from bot.states.fsm import FocusStates
from bot.utils.analytics import log_event

logger = logging.getLogger(__name__)

router = Router()


# ── Focus option A / B ─────────────────────────────────────────────────────────

@router.callback_query(FocusStates.choosing_option, F.data.startswith("focus:"))
async def on_focus_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    option = callback.data.split(":", 1)[1]  # "A" or "B"
    data = await state.get_data()
    session_id = data["session_id"]

    opt_data = data.get(f"option_{option.lower()}", {})

    result = await db.execute(
        select(DailySession).where(DailySession.id == session_id)
    )
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        await callback.answer("Сессия не найдена", show_alert=True)
        return

    session_obj.focus_option = option
    session_obj.focus_text = opt_data.get("focus", "")
    session_obj.step_text = opt_data.get("step", "")
    session_obj.plan_b_text = opt_data.get("plan_b", "")
    await db.commit()

    suggested_energy = data.get("suggested_energy", 3)

    await callback.message.edit_text(
        f"✅ Выбран вариант {option}!\n\n"
        f"🎯 {session_obj.focus_text}\n"
        f"📌 Шаг: {session_obj.step_text}\n"
        f"🔄 План Б: {session_obj.plan_b_text}\n\n"
        f"Подтверди уровень энергии (предлагаю {suggested_energy}/5):",
        reply_markup=energy_kb(suggested_energy),
    )
    await state.set_state(FocusStates.confirming_energy)
    await callback.answer()


# ── Energy confirmation ────────────────────────────────────────────────────────

@router.callback_query(FocusStates.confirming_energy, F.data.startswith("energy:"))
async def on_energy_confirmed(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    energy = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    session_id = data["session_id"]

    result = await db.execute(
        select(DailySession).where(DailySession.id == session_id)
    )
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        await callback.answer("Сессия не найдена", show_alert=True)
        return

    tz = ZoneInfo(user_db.tz_personal or "Europe/Moscow")
    now = datetime.now(tz)

    session_obj.energy = energy
    session_obj.accepted_at = now
    await db.commit()

    await log_event(db, "focus_selected", user_id=user_db.id, metadata={
        "session_id": session_id,
        "option": session_obj.focus_option,
        "energy": energy,
    })

    # Schedule checkins (+3h, +6h) and evening reminders
    try:
        await schedule_checkins(user_db, session_obj, now)
    except Exception as e:
        logger.error("Failed to schedule checkins for user %s: %s", user_db.id, e)
        await callback.message.answer(
            "⚠️ Не удалось настроить напоминания о прогрессе. "
            "Напомни мне в 3 часа и 6 часов после начала — или открой бота вручную."
        )

    try:
        schedule_evening_reminders(user_db, session_obj)
    except Exception as e:
        logger.error("Failed to schedule evening reminder for user %s: %s", user_db.id, e)

    response_text = (
        f"🚀 Поехали! Энергия: {energy}/5\n\n"
        f"🎯 {session_obj.focus_text}\n"
        f"📌 Сейчас: {session_obj.step_text}\n\n"
        "Я напомню о прогрессе через 3 часа. Удачи!"
    )

    # Offer "go deeper" if triggered
    go_deeper = data.get("go_deeper_triggered", False)

    if go_deeper:
        await callback.message.edit_text(
            response_text + "\n\n"
            "💭 Тут есть место, где полезно разложить решение подробнее. "
            "Если хочешь — можем пройтись по нему отдельно.",
            reply_markup=go_deeper_kb(session_id),
        )
    else:
        await callback.message.edit_text(response_text)

    # Ask for simple daily tasks (checklist)
    await _ask_for_todos(callback, state, db, user_db, session_id)
    await callback.answer()


async def _ask_for_todos(callback, state, db, user_db, session_id: int) -> None:
    """After focus confirmed — ask if there are simple todos to track."""
    from sqlalchemy import select
    from datetime import date, datetime
    from zoneinfo import ZoneInfo
    from bot.db.models import TodoItem

    # Find carried-over todos from previous days
    tz = ZoneInfo(user_db.tz_personal or "Europe/Moscow")
    today = datetime.now(tz).date()
    carried = await db.execute(
        select(TodoItem).where(
            TodoItem.user_id == user_db.id,
            TodoItem.date_local <= today,
            TodoItem.status == "pending",
            TodoItem.session_id.is_(None),  # not yet attached to a session
        )
    )
    carried_items = list(carried.scalars().all())

    # Attach carried-over todos to today's session
    for item in carried_items:
        item.session_id = session_id
        item.date_local = today
    if carried_items:
        await db.commit()
        schedule_todo_reminders(user_db, today)

    carried_text = ""
    if carried_items:
        names = "\n".join(f"• {t.text}" for t in carried_items)
        carried_text = f"\n\nС вчера перенесено:\n{names}"

    await state.set_state(FocusStates.entering_todos)
    await callback.message.answer(
        f"📋 Есть ещё простые дела на сегодня?{carried_text}\n\n"
        "Напиши или скажи голосом (например: «оплатить счёт, забрать посылку»).\n"
        "Или пропусти — всё ок.",
        parse_mode="Markdown",
        reply_markup=todo_input_kb(),
    )
