"""Evening report handler."""

from __future__ import annotations

import logging

from aiogram import Bot, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, DailySession, EveningReport
from bot.keyboards.inline import main_menu_kb, voice_confirm_kb
from bot.states.fsm import EveningStates
from bot.utils.analytics import log_event

logger = logging.getLogger(__name__)

router = Router()


# ── Status selection (from scheduled notification) ─────────────────────────────

@router.callback_query(F.data.startswith("evening:"))
async def on_evening_status(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка", show_alert=True)
        return

    _, session_id_str, status = parts
    session_id = int(session_id_str)

    # Verify
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

    status_emoji = {"done": "✅", "partial": "🟡", "fail": "❌"}.get(status, "")

    await state.update_data(
        evening_session_id=session_id,
        evening_status=status,
    )
    await state.set_state(EveningStates.waiting_text)

    await callback.message.edit_text(
        f"Статус дня: {status_emoji}\n\n"
        "Напиши или скажи голосом:\n"
        "1. Что сделал?\n"
        "2. Что помогло или помешало?\n"
        "3. Первый шаг завтра?"
    )
    await callback.answer()


# ── Evening text ───────────────────────────────────────────────────────────────

@router.message(EveningStates.waiting_text, F.text)
async def on_evening_text(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    data = await state.get_data()
    session_id = data["evening_session_id"]
    status = data["evening_status"]
    text = message.text.strip()

    # Check for existing report
    existing = await db.execute(
        select(EveningReport).where(EveningReport.daily_session_id == session_id)
    )
    report = existing.scalar_one_or_none()
    if report:
        report.status = status
        report.text = text
    else:
        report = EveningReport(
            daily_session_id=session_id,
            status=status,
            text=text,
        )
        db.add(report)
    await db.commit()

    await log_event(db, "evening_report_done", user_id=user_db.id, metadata={
        "session_id": session_id, "status": status,
    })

    status_emoji = {"done": "✅", "partial": "🟡", "fail": "❌"}.get(status, "")
    await message.answer(
        f"📝 День закрыт {status_emoji}\n\n"
        "Спасибо за отчёт. Отдыхай и набирайся сил на завтра! 🌙",
        reply_markup=main_menu_kb(),
    )
    await state.clear()


# ── Voice evening report ──────────────────────────────────────────────────────

@router.message(EveningStates.waiting_text, F.voice)
async def on_evening_voice(
    message: Message,
    bot: Bot,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    from bot.services.transcriber import transcriber
    import tempfile
    from pathlib import Path

    file = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await bot.download_file(file.file_path, tmp_path)

    try:
        text = await transcriber.transcribe(tmp_path)
    except Exception as e:
        logger.error("Evening voice transcription failed: %s", e)
        await message.answer("Не удалось распознать. Напиши текстом.")
        return
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not text.strip():
        await message.answer("Не удалось распознать речь. Напиши текстом.")
        return

    await state.update_data(voice_pending_evening=text)
    await message.answer(
        f"🎙 _{text}_\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=voice_confirm_kb("evening"),
    )


@router.callback_query(EveningStates.waiting_text, F.data == "vc_ok:evening")
async def confirm_voice_evening(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    text = data.get("voice_pending_evening", "")
    if not text:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await callback.answer()
    await callback.message.delete()
    # Reuse text handler
    callback.message.text = text
    await on_evening_text(callback.message, state, db, user_db)


@router.callback_query(EveningStates.waiting_text, F.data == "vc_edit:evening")
async def edit_voice_evening(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "✏️ Напиши исправленный вариант:\n"
        "1. Что сделал?\n"
        "2. Что помогло или помешало?\n"
        "3. Первый шаг завтра?"
    )
    await callback.answer()
