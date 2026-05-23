"""Weekly and monthly context handler."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from aiogram import Bot, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, UserContext
from bot.keyboards.inline import context_period_kb, main_menu_kb, voice_confirm_kb
from bot.services.transcriber import transcriber
from bot.states.fsm import ContextStates

logger = logging.getLogger(__name__)
router = Router()


async def _get_context(db: AsyncSession, user_id: int, period: str) -> UserContext | None:
    result = await db.execute(
        select(UserContext).where(
            UserContext.user_id == user_id,
            UserContext.period == period,
        )
    )
    return result.scalar_one_or_none()


async def _save_context(
    db: AsyncSession,
    user_db: User,
    period: str,
    text: str,
) -> UserContext:
    context = await _get_context(db, user_db.id, period)
    if context:
        context.text = text
    else:
        context = UserContext(user_id=user_db.id, period=period, text=text)
        db.add(context)
    await db.commit()
    await db.refresh(context)
    return context


async def _show_context_menu(message: Message, db: AsyncSession, user_db: User) -> None:
    week = await _get_context(db, user_db.id, "week")
    month = await _get_context(db, user_db.id, "month")
    await message.answer(
        "📌 *Контекст для «Моего дня»*\n\n"
        f"*Неделя:*\n{week.text if week and week.text else 'не задан'}\n\n"
        f"*Месяц:*\n{month.text if month and month.text else 'не задан'}\n\n"
        "Выбери, что обновить:",
        parse_mode="Markdown",
        reply_markup=context_period_kb(),
    )


async def _transcribe_voice(message: Message, bot: Bot) -> str | None:
    file = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await bot.download_file(file.file_path, tmp_path)
    try:
        text = await transcriber.transcribe(tmp_path)
        return text.strip() or None
    except Exception as exc:
        logger.error("Context transcription failed: %s", exc)
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.message(F.text == "📌 Контекст")
async def context_button(
    message: Message,
    db: AsyncSession,
    user_db: User,
) -> None:
    if not user_db.onboarding_complete:
        await message.answer("Сначала пройди настройку: /start")
        return
    await _show_context_menu(message, db, user_db)


@router.callback_query(F.data == "set:context")
async def context_from_settings(
    callback: CallbackQuery,
    db: AsyncSession,
    user_db: User,
) -> None:
    await _show_context_menu(callback.message, db, user_db)
    await callback.answer()


@router.callback_query(F.data.startswith("context:"))
async def choose_context_period(callback: CallbackQuery, state: FSMContext) -> None:
    period = callback.data.split(":", 1)[1]
    label = "недели" if period == "week" else "месяца"
    await state.set_state(ContextStates.editing_context)
    await state.update_data(context_period=period)
    await callback.message.edit_text(
        f"Наговори или напиши контекст {label}: что сейчас происходит, чем ты занимаешься, "
        "какие проекты/люди/ограничения важны, что нужно учитывать в утренних выгрузках."
    )
    await callback.answer()


@router.message(ContextStates.editing_context, F.text)
async def save_context_text(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    data = await state.get_data()
    period = data.get("context_period", "week")
    text = message.text.strip()
    if len(text) < 5:
        await message.answer("Слишком коротко. Напиши или наговори чуть больше контекста.")
        return

    await _save_context(db, user_db, period, text)
    label = "недели" if period == "week" else "месяца"
    await message.answer(
        f"✅ Контекст {label} обновлен.\n\n"
        "Теперь утренние выгрузки будут читаться с учетом этого фона.",
        reply_markup=main_menu_kb(),
    )
    await state.clear()


@router.message(ContextStates.editing_context, F.voice)
async def save_context_voice(
    message: Message,
    bot: Bot,
    state: FSMContext,
) -> None:
    text = await _transcribe_voice(message, bot)
    if not text:
        await message.answer("Не удалось распознать голосовое. Напиши текстом или попробуй еще раз.")
        return
    await state.update_data(voice_pending_context=text)
    await message.answer(
        f"🎙 _{text}_\n\nВсе верно?",
        parse_mode="Markdown",
        reply_markup=voice_confirm_kb("context"),
    )


@router.callback_query(ContextStates.editing_context, F.data == "vc_ok:context")
async def confirm_context_voice(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    data = await state.get_data()
    text = data.get("voice_pending_context", "")
    if not text:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await callback.answer()
    await callback.message.delete()
    period = data.get("context_period", "week")
    await _save_context(db, user_db, period, text)
    label = "недели" if period == "week" else "месяца"
    await callback.message.answer(
        f"✅ Контекст {label} обновлен.\n\n"
        "Теперь утренние выгрузки будут читаться с учетом этого фона.",
        reply_markup=main_menu_kb(),
    )
    await state.clear()


@router.callback_query(ContextStates.editing_context, F.data == "vc_edit:context")
async def edit_context_voice(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Напиши исправленный контекст:")
    await callback.answer()
