"""Go deeper — coaching mini-session triggered by LLM detection."""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, DailySession
from bot.keyboards.inline import main_menu_kb
from bot.services.coach_engine import coach
from bot.states.fsm import DeeperStates
from bot.utils.analytics import log_event

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data.startswith("deeper:"))
async def on_go_deeper(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    session_id = int(callback.data.split(":", 1)[1])

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

    await log_event(db, "go_deeper_started", user_id=user_db.id, metadata={
        "session_id": session_id,
    })

    await callback.message.edit_text("🔍 Копаем глубже...")

    try:
        response = await coach.go_deeper(
            dump_text=session_obj.dump_text or "",
            emotion_mirror=session_obj.llm_response_json.get("emotion_mirror", "") if session_obj.llm_response_json else "",
            tone=user_db.tone,
        )
    except Exception as e:
        logger.error("Go deeper LLM failed: %s", e)
        await callback.message.edit_text(
            "Не удалось запустить глубинную сессию. Попробуй позже."
        )
        return

    await callback.message.edit_text(
        f"🔍 *Копаем глубже*\n\n{response}\n\n"
        "Напиши свои мысли в ответ, или отправь голосовое. "
        "Когда закончишь — напиши «готово».",
        parse_mode="Markdown",
    )
    await state.set_state(DeeperStates.in_session)
    await state.update_data(deeper_session_id=session_id)
    await callback.answer()


@router.message(DeeperStates.in_session, F.text)
async def on_deeper_response(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    text = message.text.strip().lower()

    if text in ("готово", "done", "хватит", "стоп"):
        await log_event(db, "go_deeper_completed", user_id=user_db.id)
        await message.answer(
            "🙏 Спасибо за честность с собой. "
            "Это важный шаг. Возвращайся к фокусу дня!",
            reply_markup=main_menu_kb(),
        )
        await state.clear()
        return

    # Continue the conversation — acknowledge
    await message.answer(
        "Слышу тебя. Продолжай размышлять или напиши «готово» когда будешь готов(а) вернуться к фокусу дня."
    )


@router.message(DeeperStates.in_session, F.voice)
async def on_deeper_voice(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    await message.answer(
        "Получил голосовое. Продолжай размышлять или напиши «готово» когда будешь готов(а)."
    )
