"""Living profile onboarding and editing."""

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
from bot.keyboards.inline import main_menu_kb, profile_confirm_kb, profile_view_kb, voice_confirm_kb
from bot.services.profile_engine import (
    PROFILE_PERIOD,
    extract_profile,
    format_profile,
    parse_profile,
    serialize_profile,
)
from bot.services.scheduler_service import schedule_morning_reminders
from bot.services.transcriber import transcriber
from bot.states.fsm import ProfileStates
from bot.utils.analytics import log_event

logger = logging.getLogger(__name__)
router = Router()


PROFILE_INTRO = (
    "Расскажи, как сейчас устроена твоя жизнь.\n\n"
    "Можно голосом, текстом и хаотично. Я сама вытащу роли, важные проекты, нагрузки "
    "и то, как тебе лучше помогать.\n\n"
    "Подсказки:\n"
    "• что сейчас на тебе\n"
    "• что тянет внимание\n"
    "• что важно не потерять\n"
    "• что постоянно переносится\n"
    "• как с тобой говорить\n\n"
    "Например: «Я в декрете, ребёнок маленький, плохо сплю, веду проект, дома много быта. "
    "Хочу не потерять доход. Мне лучше коротко и по делу»."
)


async def _get_profile_context(db: AsyncSession, user_id: int) -> UserContext | None:
    result = await db.execute(
        select(UserContext).where(
            UserContext.user_id == user_id,
            UserContext.period == PROFILE_PERIOD,
        )
    )
    return result.scalar_one_or_none()


async def _save_profile_context(
    db: AsyncSession,
    user_db: User,
    profile: dict,
) -> UserContext:
    context = await _get_profile_context(db, user_db.id)
    text = serialize_profile(profile)
    if context:
        context.text = text
    else:
        context = UserContext(user_id=user_db.id, period=PROFILE_PERIOD, text=text)
        db.add(context)
    await db.commit()
    await db.refresh(context)
    return context


async def _transcribe_voice(message: Message, bot: Bot) -> str | None:
    file = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await bot.download_file(file.file_path, tmp_path)
    try:
        text = await transcriber.transcribe(tmp_path)
        return text.strip() or None
    except Exception as exc:
        logger.error("Profile transcription failed: %s", exc)
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def ask_profile_onboarding(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileStates.collecting)
    await state.update_data(profile_mode="onboarding")
    await message.answer(PROFILE_INTRO)


async def _build_and_show_draft(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
    text: str,
) -> None:
    data = await state.get_data()
    base_profile = data.get("pending_profile")
    if not isinstance(base_profile, dict):
        context = await _get_profile_context(db, user_db.id)
        base_profile = parse_profile(context.text if context else None)

    status_msg = await message.answer("Собираю профиль из твоего рассказа...")
    profile = await extract_profile(text, base_profile)
    await state.update_data(pending_profile=profile)
    await state.set_state(ProfileStates.confirming)

    await status_msg.edit_text(
        "Я так поняла твой профиль:\n\n"
        f"{format_profile(profile)}\n\n"
        "Всё верно?",
        reply_markup=profile_confirm_kb(),
    )


@router.message(F.text == "👤 Профиль")
async def profile_button(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    if not user_db.onboarding_complete:
        await ask_profile_onboarding(message, state)
        return

    context = await _get_profile_context(db, user_db.id)
    profile = parse_profile(context.text if context else None)
    await message.answer(
        "👤 Твой профиль:\n\n"
        f"{format_profile(profile)}",
        reply_markup=profile_view_kb(),
    )


@router.callback_query(F.data == "set:profile")
async def profile_from_settings(
    callback: CallbackQuery,
    db: AsyncSession,
    user_db: User,
) -> None:
    context = await _get_profile_context(db, user_db.id)
    profile = parse_profile(context.text if context else None)
    await callback.message.edit_text(
        "👤 Твой профиль:\n\n"
        f"{format_profile(profile)}",
        reply_markup=profile_view_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "profile:update")
async def start_profile_update(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileStates.collecting)
    await state.update_data(profile_mode="update")
    await callback.message.edit_text(
        "Наговори или напиши, что изменилось: что добавить, убрать, ослабить или как теперь лучше помогать."
    )
    await callback.answer()


@router.message(ProfileStates.collecting, F.text)
async def collect_profile_text(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    text = message.text.strip()
    if len(text) < 10:
        await message.answer("Слишком коротко. Расскажи чуть больше, можно хаотично.")
        return
    await _build_and_show_draft(message, state, db, user_db, text)


@router.message(ProfileStates.collecting, F.voice)
async def collect_profile_voice(
    message: Message,
    bot: Bot,
    state: FSMContext,
) -> None:
    text = await _transcribe_voice(message, bot)
    if not text:
        await message.answer("Не удалось распознать голосовое. Напиши текстом или попробуй ещё раз.")
        return
    await state.update_data(voice_pending_profile=text)
    await message.answer(
        f"🎙 _{text}_\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=voice_confirm_kb("profile"),
    )


@router.callback_query(ProfileStates.collecting, F.data == "vc_ok:profile")
async def confirm_profile_voice(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    data = await state.get_data()
    text = data.get("voice_pending_profile", "")
    if not text:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await callback.answer()
    await callback.message.delete()
    await _build_and_show_draft(callback.message, state, db, user_db, text)


@router.callback_query(ProfileStates.collecting, F.data == "vc_edit:profile")
async def edit_profile_voice(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Напиши исправленный вариант:")
    await callback.answer()


@router.callback_query(ProfileStates.confirming, F.data == "profile:edit")
async def edit_profile_draft(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileStates.collecting)
    await callback.message.edit_text(
        "Напиши или наговори поправку обычными словами. Я обновлю черновик профиля и снова покажу."
    )
    await callback.answer()


@router.callback_query(ProfileStates.confirming, F.data == "profile:save")
async def save_profile_draft(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    data = await state.get_data()
    profile = data.get("pending_profile")
    if not isinstance(profile, dict):
        await callback.answer("Профиль не найден", show_alert=True)
        return

    await _save_profile_context(db, user_db, profile)
    mode = data.get("profile_mode", "update")
    if mode == "onboarding":
        user_db.onboarding_complete = True
        user_db.morning_ping_time = user_db.morning_ping_time or "09:00"
        user_db.evening_report_time = user_db.evening_report_time or "21:00"
        await db.commit()
        schedule_morning_reminders(user_db)
        await log_event(db, "onboarding_complete", user_id=user_db.id, metadata={"mode": "profile"})
        text = (
            "✅ Профиль сохранён.\n\n"
            "Теперь я буду использовать его в утренних пингах и разборе дня.\n"
            "Утренний пинг поставила на 09:00, вечернее закрытие — на 21:00. Это можно поменять в настройках."
        )
    else:
        await log_event(db, "profile_updated", user_id=user_db.id)
        text = "✅ Профиль обновлён. Буду учитывать это в следующих разборах."

    await callback.message.edit_text(text)
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await state.clear()
    await callback.answer()
