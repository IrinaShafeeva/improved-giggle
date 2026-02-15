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
from bot.keyboards.inline import energy_kb, go_deeper_kb, main_menu_kb
from bot.services.scheduler_service import schedule_checkins, schedule_evening_reminders
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
    await schedule_checkins(user_db, session_obj, now)
    schedule_evening_reminders(user_db, session_obj)

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
            "💭 Я заметил в твоём дампе сигналы тревоги или перегрузки. "
            "Если хочешь — можем разобраться глубже.",
            reply_markup=go_deeper_kb(session_id),
        )
    else:
        await callback.message.edit_text(response_text)

    await state.clear()
    await callback.answer()
