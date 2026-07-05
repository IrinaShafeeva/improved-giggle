"""User settings handler."""

from __future__ import annotations

import logging

import tempfile
from pathlib import Path

from aiogram import Bot, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, Focus
from bot.keyboards.inline import settings_kb, tone_kb, time_picker_kb, main_menu_kb, focus_view_kb, voice_confirm_kb
from bot.services.scheduler_service import schedule_morning_reminders
from bot.states.fsm import SettingsStates

logger = logging.getLogger(__name__)

router = Router()


# ── Entry points ──────────────────────────────────────────────────────────────

@router.message(F.text == "⚙️ Настройки")
async def settings_button(message: Message, user_db: User) -> None:
    if not user_db.onboarding_complete:
        await message.answer("Сначала пройди настройку: /start")
        return

    await message.answer(
        "⚙️ *Настройки*\n\n"
        f"Тон: {user_db.tone}\n"
        f"Утренний пинг: {user_db.morning_ping_time or 'не задан'}\n"
        f"Вечерний отчёт: {user_db.evening_report_time or 'не задан'}\n\n"
        "Что изменить?",
        parse_mode="Markdown",
        reply_markup=settings_kb(),
    )


# ── Setting callbacks ────────────────────────────────────────────────────────

@router.callback_query(F.data == "set:tone")
async def set_tone(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Выбери тон:",
        reply_markup=tone_kb(),
    )
    await state.set_state(SettingsStates.editing_value)
    await state.update_data(setting_key="tone")
    await callback.answer()


@router.callback_query(F.data == "set:morning_time")
async def set_morning_time(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Выбери время утреннего пинга:",
        reply_markup=time_picker_kb("morning"),
    )
    await state.set_state(SettingsStates.editing_value)
    await state.update_data(setting_key="morning_time")
    await callback.answer()


@router.callback_query(F.data == "set:evening_time")
async def set_evening_time(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Выбери время вечернего отчёта:",
        reply_markup=time_picker_kb("evening"),
    )
    await state.set_state(SettingsStates.editing_value)
    await state.update_data(setting_key="evening_time")
    await callback.answer()


@router.callback_query(F.data == "set:weekly_focus")
async def set_weekly_focus(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Напиши или скажи голосом новый фокус недели:")
    await state.set_state(SettingsStates.editing_value)
    await state.update_data(setting_key="weekly_focus")
    await callback.answer()


@router.callback_query(F.data == "set:monthly_focus")
async def set_monthly_focus(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Напиши или скажи голосом новый фокус месяца:")
    await state.set_state(SettingsStates.editing_value)
    await state.update_data(setting_key="monthly_focus")
    await callback.answer()


# ── Handle inline value changes (tone, times) ─────────────────────────────────

@router.callback_query(SettingsStates.editing_value, F.data.startswith("tone:"))
async def on_tone_edit(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    tone = callback.data.split(":", 1)[1]
    user_db.tone = tone
    await db.commit()
    await callback.message.edit_text(f"✅ Тон изменён: {tone}")
    await state.clear()
    await callback.answer()


@router.callback_query(
    SettingsStates.editing_value, F.data.startswith("morning_time:")
)
async def on_morning_edit(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    time_str = callback.data.split(":", 1)[1]
    user_db.morning_ping_time = time_str
    await db.commit()
    schedule_morning_reminders(user_db)
    await callback.message.edit_text(f"✅ Утренний пинг: {time_str}")
    await state.clear()
    await callback.answer()


@router.callback_query(
    SettingsStates.editing_value, F.data.startswith("evening_time:")
)
async def on_evening_edit(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    time_str = callback.data.split(":", 1)[1]
    user_db.evening_report_time = time_str
    await db.commit()
    await callback.message.edit_text(f"✅ Вечерний отчёт: {time_str}")
    await state.clear()
    await callback.answer()


# ── Handle text value changes (focuses) ────────────────────────────────────────

@router.message(SettingsStates.editing_value, F.text)
async def on_text_setting(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    data = await state.get_data()
    key = data.get("setting_key")
    text = message.text.strip()

    if key in ("weekly_focus", "monthly_focus"):
        period = "week" if key == "weekly_focus" else "month"
        result = await db.execute(
            select(Focus).where(
                Focus.user_id == user_db.id,
                Focus.period == period,
                Focus.is_active.is_(True),
            )
        )
        focus = result.scalars().first()
        if focus:
            focus.text = text
        else:
            focus = Focus(user_id=user_db.id, period=period, text=text, is_active=True)
            db.add(focus)
        await db.commit()
        label = "недели" if period == "week" else "месяца"
        await message.answer(
            f"✅ Фокус {label} обновлён: {text}",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer("Не понял. Попробуй ещё раз.")
        return

    await state.clear()


@router.message(SettingsStates.editing_value, F.voice)
async def on_voice_setting(
    message: Message,
    bot: Bot,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    from bot.services.transcriber import transcriber

    file = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await bot.download_file(file.file_path, tmp_path)

    try:
        text = await transcriber.transcribe(tmp_path)
    except Exception as e:
        logger.error("Settings voice transcription failed: %s", e)
        await message.answer("Не удалось распознать. Напиши текстом.")
        return
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not text.strip():
        await message.answer("Не удалось распознать речь. Напиши текстом.")
        return

    await state.update_data(voice_pending_settings=text)
    await message.answer(
        f"🎙 _{text}_\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=voice_confirm_kb("settings"),
    )


@router.callback_query(SettingsStates.editing_value, F.data == "vc_ok:settings")
async def confirm_voice_settings(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    text = data.get("voice_pending_settings", "")
    if not text:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await callback.answer()
    await callback.message.delete()
    callback.message.text = text
    await on_text_setting(callback.message, state, db, user_db)


@router.callback_query(SettingsStates.editing_value, F.data == "vc_edit:settings")
async def edit_voice_settings(callback: CallbackQuery) -> None:
    await callback.message.edit_text("✏️ Напиши исправленный вариант:")
    await callback.answer()


# ── Focus view buttons from main menu ──────────────────────────────────────────

@router.message(F.text == "📅 Фокус недели")
async def view_weekly_focus(
    message: Message, db: AsyncSession, user_db: User
) -> None:
    if not user_db.onboarding_complete:
        await message.answer("Сначала пройди настройку: /start")
        return
    result = await db.execute(
        select(Focus).where(
            Focus.user_id == user_db.id,
            Focus.period == "week",
            Focus.is_active.is_(True),
        )
    )
    focuses = result.scalars().all()
    if focuses:
        lines = []
        for f in focuses:
            sphere_name = f.sphere.name if f.sphere else ""
            lines.append(f"• {sphere_name}: {f.text}" if sphere_name else f"• {f.text}")
        text = "\n".join(lines)
    else:
        text = "Не задан"
    await message.answer(
        f"📅 *Фокус недели*:\n{text}",
        parse_mode="Markdown",
        reply_markup=focus_view_kb("week"),
    )


@router.message(F.text == "🗓 Фокус месяца")
async def view_monthly_focus(
    message: Message, db: AsyncSession, user_db: User
) -> None:
    if not user_db.onboarding_complete:
        await message.answer("Сначала пройди настройку: /start")
        return
    result = await db.execute(
        select(Focus).where(
            Focus.user_id == user_db.id,
            Focus.period == "month",
            Focus.is_active.is_(True),
        )
    )
    focuses = result.scalars().all()
    if focuses:
        lines = []
        for f in focuses:
            sphere_name = f.sphere.name if f.sphere else ""
            lines.append(f"• {sphere_name}: {f.text}" if sphere_name else f"• {f.text}")
        text = "\n".join(lines)
    else:
        text = "Не задан"
    await message.answer(
        f"🗓 *Фокус месяца*:\n{text}",
        parse_mode="Markdown",
        reply_markup=focus_view_kb("month"),
    )
