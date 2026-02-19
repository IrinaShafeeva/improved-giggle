"""Mind dump handler — voice or text input -> LLM analysis -> focus selection."""

from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, Focus, DailySession
from bot.keyboards.inline import (
    focus_options_kb,
    energy_kb,
    go_deeper_kb,
    main_menu_kb,
)
from bot.services.coach_engine import coach, DumpAnalysis
from bot.services.transcriber import transcriber
from bot.states.fsm import DumpStates, FocusStates
from bot.utils.analytics import log_event

logger = logging.getLogger(__name__)

router = Router()


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_focuses(db: AsyncSession, user_id: int) -> tuple[str, str]:
    result = await db.execute(
        select(Focus).where(Focus.user_id == user_id, Focus.is_active.is_(True))
    )
    all_focuses = result.scalars().all()
    weekly = ", ".join(f.text for f in all_focuses if f.period == "week")
    monthly = ", ".join(f.text for f in all_focuses if f.period == "month")
    return weekly, monthly


def _format_analysis(a: DumpAnalysis) -> str:
    lines = []
    if a.emotion_mirror:
        lines.append(f"🪞 *Зеркало эмоций*\n{a.emotion_mirror}")
    if a.need_meaning:
        lines.append(f"💡 *Потребность*\n{a.need_meaning}")
    if a.tasks:
        tasks_text = "\n".join(f"  • {t}" for t in a.tasks)
        lines.append(f"📋 *Задачи*\n{tasks_text}")
    if a.focus_mapping:
        lines.append(f"🎯 *Связь с фокусом*\n{a.focus_mapping}")

    if a.option_a:
        lines.append(
            f"🅰️ *Вариант A: {a.option_a.focus_text}*\n"
            f"  Шаг (30-45 мин): {a.option_a.step_text}\n"
            f"  План Б (10 мин): {a.option_a.plan_b_text}"
        )
    if a.option_b:
        lines.append(
            f"🅱️ *Вариант B: {a.option_b.focus_text}*\n"
            f"  Шаг (30-45 мин): {a.option_b.step_text}\n"
            f"  План Б (10 мин): {a.option_b.plan_b_text}"
        )

    lines.append(f"⚡ *Энергия*: {a.suggested_energy}/5")

    return "\n\n".join(lines)


def _user_today(user: User) -> date:
    tz = ZoneInfo(user.tz_personal or "Europe/Moscow")
    return datetime.now(tz).date()


# ── Entry points (button or command or direct message) ─────────────────────────

@router.message(F.text == "🧠 Dump")
async def dump_button(message: Message, state: FSMContext, user_db: User) -> None:
    if not user_db.onboarding_complete:
        await message.answer("Сначала пройди настройку: /start")
        return
    await message.answer(
        "Отправь голосовое сообщение или напиши текст — "
        "выгрузи всё, что в голове прямо сейчас. 🧠"
    )
    await state.set_state(DumpStates.waiting_dump)


@router.message(F.text == "🎯 Фокус дня")
async def focus_day_button(
    message: Message, db: AsyncSession, user_db: User
) -> None:
    today = _user_today(user_db)
    result = await db.execute(
        select(DailySession).where(
            DailySession.user_id == user_db.id,
            DailySession.date_local == today,
        )
    )
    session = result.scalar_one_or_none()
    if session and session.focus_text:
        await message.answer(
            f"🎯 *Фокус дня*: {session.focus_text}\n"
            f"📌 Шаг: {session.step_text or '—'}\n"
            f"🔄 План Б: {session.plan_b_text or '—'}\n"
            f"⚡ Энергия: {session.energy or '—'}/5",
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            "У тебя ещё нет фокуса на сегодня. Сделай mind dump: 🧠 Dump"
        )


# ── Morning ping callback handlers ─────────────────────────────────────────────

@router.callback_query(F.data == "dump_yes")
async def on_dump_yes(
    callback: CallbackQuery,
    state: FSMContext,
    user_db: User,
) -> None:
    if not user_db.onboarding_complete:
        await callback.answer("Сначала пройди настройку: /start", show_alert=True)
        return

    await callback.message.edit_text(
        "Отправь голосовое сообщение или напиши текст — "
        "выгрузи всё, что в голове прямо сейчас. 🧠"
    )
    await state.set_state(DumpStates.waiting_dump)
    await callback.answer()


@router.callback_query(F.data == "dump_later")
async def on_dump_later(
    callback: CallbackQuery,
) -> None:
    await callback.message.edit_text(
        "Ок, напомню позже. Когда будешь готов(а) — "
        "нажми 🧠 Dump или просто отправь голосовое."
    )
    await callback.answer()


# ── Voice message handler ─────────────────────────────────────────────────────

@router.message(DumpStates.waiting_dump, F.voice)
async def on_voice_dump(
    message: Message,
    bot: Bot,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    await message.answer("🎙 Транскрибирую голосовое...")

    # Download voice file
    file = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await bot.download_file(file.file_path, tmp_path)

    try:
        text = await transcriber.transcribe(tmp_path)
    except Exception as e:
        logger.error("Transcription failed: %s", e)
        await message.answer("Не удалось распознать голосовое. Попробуй ещё раз или напиши текстом.")
        return
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not text.strip():
        await message.answer("Не удалось распознать речь. Попробуй ещё раз.")
        return

    await _process_dump(message, state, db, user_db, text, is_voice=True)


# ── Text message handler ──────────────────────────────────────────────────────

@router.message(DumpStates.waiting_dump, F.text)
async def on_text_dump(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    text = message.text.strip()
    if len(text) < 10:
        await message.answer("Напиши побольше — хотя бы пару предложений, чтобы было что анализировать.")
        return

    await _process_dump(message, state, db, user_db, text, is_voice=False)


# ── Also handle voice/text outside FSM state (direct send) ────────────────────

@router.message(F.voice)
async def on_voice_direct(
    message: Message,
    bot: Bot,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    if not user_db.onboarding_complete:
        await message.answer("Сначала пройди настройку: /start")
        return

    # Check if there's already a session today
    today = _user_today(user_db)
    result = await db.execute(
        select(DailySession).where(
            DailySession.user_id == user_db.id,
            DailySession.date_local == today,
            DailySession.accepted_at.isnot(None),
        )
    )
    if result.scalar_one_or_none():
        await message.answer("У тебя уже есть фокус на сегодня! Используй 🎯 Фокус дня чтобы посмотреть.")
        return

    await state.set_state(DumpStates.waiting_dump)
    await on_voice_dump(message, bot, state, db, user_db)


# ── Direct text message outside FSM (user just sends text in private chat) ────

@router.message(F.text & ~F.text.startswith("/"))
async def on_text_direct(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    # Skip menu button texts
    menu_texts = {"🧠 Dump", "🎯 Фокус дня", "📅 Фокус недели", "🗓 Фокус месяца", "⚙️ Настройки"}
    if message.text.strip() in menu_texts:
        return  # handled by other routers

    if not user_db.onboarding_complete:
        return  # silently ignore — onboarding handlers will pick up

    # Check if there's already an accepted session today
    today = _user_today(user_db)
    result = await db.execute(
        select(DailySession).where(
            DailySession.user_id == user_db.id,
            DailySession.date_local == today,
            DailySession.accepted_at.isnot(None),
        )
    )
    if result.scalar_one_or_none():
        # User has a focus today; don't treat random text as dump
        return

    text = message.text.strip()
    if len(text) < 10:
        return  # too short, probably not a dump

    await state.set_state(DumpStates.waiting_dump)
    await on_text_dump(message, state, db, user_db)


# ── Core processing ───────────────────────────────────────────────────────────

async def _process_dump(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
    text: str,
    is_voice: bool,
) -> None:
    today = _user_today(user_db)

    # Dedup: если уже есть подтверждённый фокус сегодня — не создаём новую сессию
    existing_result = await db.execute(
        select(DailySession).where(
            DailySession.user_id == user_db.id,
            DailySession.date_local == today,
            DailySession.accepted_at.isnot(None),
        )
    )
    if existing_result.scalar_one_or_none():
        await message.answer(
            "У тебя уже есть фокус на сегодня! Нажми 🎯 Фокус дня чтобы посмотреть."
        )
        await state.clear()
        return

    await message.answer("🤔 Анализирую...")

    weekly_focus, monthly_focus = await _get_focuses(db, user_db.id)

    analysis = await coach.analyze_mind_dump(
        text=text,
        weekly_focus=weekly_focus,
        monthly_focus=monthly_focus,
        tone=user_db.tone,
        spheres=", ".join(s.name for s in user_db.spheres) if user_db.spheres else "",
    )

    # Reuse незавершённую сессию за сегодня (если была — пользователь начал dump и вышел)
    existing2 = await db.execute(
        select(DailySession).where(
            DailySession.user_id == user_db.id,
            DailySession.date_local == today,
        )
    )
    session_obj = existing2.scalar_one_or_none()

    if session_obj:
        session_obj.dump_text = text
        session_obj.is_voice = is_voice
        session_obj.energy = analysis.suggested_energy
        session_obj.llm_response_json = analysis.raw
    else:
        session_obj = DailySession(
            user_id=user_db.id,
            date_local=today,
            dump_text=text,
            is_voice=is_voice,
            energy=analysis.suggested_energy,
            llm_response_json=analysis.raw,
        )
        db.add(session_obj)

    # Store option_a as default (user will choose)
    if analysis.option_a:
        session_obj.focus_text = analysis.option_a.focus_text
        session_obj.step_text = analysis.option_a.step_text
        session_obj.plan_b_text = analysis.option_a.plan_b_text
    await db.commit()
    await db.refresh(session_obj)

    await log_event(db, "dump_created", user_id=user_db.id, metadata={
        "is_voice": is_voice, "session_id": session_obj.id
    })

    # Send analysis
    formatted = _format_analysis(analysis)
    await message.answer(formatted, parse_mode="Markdown")

    # Focus choice
    await message.answer(
        "Какой вариант выбираешь?",
        reply_markup=focus_options_kb(),
    )

    # Store analysis in FSM for focus selection
    await state.update_data(
        session_id=session_obj.id,
        analysis_raw=analysis.raw,
        option_a={
            "focus": analysis.option_a.focus_text if analysis.option_a else "",
            "step": analysis.option_a.step_text if analysis.option_a else "",
            "plan_b": analysis.option_a.plan_b_text if analysis.option_a else "",
        },
        option_b={
            "focus": analysis.option_b.focus_text if analysis.option_b else "",
            "step": analysis.option_b.step_text if analysis.option_b else "",
            "plan_b": analysis.option_b.plan_b_text if analysis.option_b else "",
        },
        suggested_energy=analysis.suggested_energy,
        go_deeper_triggered=analysis.go_deeper_triggered,
        dump_text=text,
        emotion_mirror=analysis.emotion_mirror,
    )
    await state.set_state(FocusStates.choosing_option)
