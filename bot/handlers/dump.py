"""Mind dump handler — voice or text input -> mirror, structure and tasks."""

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

from bot.db.models import User, Focus, DailySession, UserContext, TodoItem
from bot.keyboards.inline import (
    carried_tasks_kb,
    main_menu_kb,
    tasks_review_kb,
    voice_confirm_kb,
)
from bot.services.coach_engine import coach, DumpAnalysis
from bot.services.transcriber import transcriber
from bot.states.fsm import DumpStates
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


async def _get_contexts(db: AsyncSession, user_id: int) -> tuple[str, str]:
    result = await db.execute(
        select(UserContext).where(UserContext.user_id == user_id)
    )
    contexts = result.scalars().all()
    weekly = next((c.text for c in contexts if c.period == "week"), "")
    monthly = next((c.text for c in contexts if c.period == "month"), "")
    return weekly, monthly


def _format_analysis(a: DumpAnalysis) -> str:
    lines = []
    if a.emotion_mirror:
        lines.append(f"🪞 *Коротко*\n{a.emotion_mirror}")
    if a.structure:
        structure_text = "\n".join(f"  • {item}" for item in a.structure)
        lines.append(f"🧩 *Структура*\n{structure_text}")
    if a.tasks:
        tasks_text = "\n".join(f"  • {t}" for t in a.tasks)
        lines.append(f"📋 *Задачи*\n{tasks_text}")
    if a.blind_spots:
        blind_spots_text = "\n".join(f"  • {item}" for item in a.blind_spots)
        lines.append(f"🔎 *Гипотезы по решениям*\n{blind_spots_text}")
    if a.main_tension:
        lines.append(f"⚡ *Главная развилка*\n{a.main_tension}")
    if a.day_risk:
        lines.append(f"📍 *Точка внимания*\n{a.day_risk}")
    if a.context_links:
        lines.append(f"📌 *Связь с контекстом*\n{a.context_links}")
    if a.sharp_question:
        lines.append(f"❓ *Один точный вопрос*\n{a.sharp_question}")
    if a.day_summary:
        lines.append(f"🎯 *Следующий ход*\n{a.day_summary}")

    return "\n\n".join(lines)


def _user_today(user: User) -> date:
    tz = ZoneInfo(user.tz_personal or "Europe/Moscow")
    return datetime.now(tz).date()


# ── Entry points (button or command or direct message) ─────────────────────────

@router.message(F.text.in_({"🧠 Выгрузка", "🧠 Dump"}))
async def dump_button(message: Message, state: FSMContext, user_db: User) -> None:
    if not user_db.onboarding_complete:
        await message.answer("Сначала пройди настройку: /start")
        return
    await message.answer(
        "Отправь голосовое или текст — выгрузи всё, что в голове прямо сейчас. "
        "Я отражу чувства, структуру, незаметные мысли и задачи."
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
    status_msg = await message.answer("🎙 Транскрибирую голосовое...")

    # Download voice file
    file = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await bot.download_file(file.file_path, tmp_path)

    try:
        text = await transcriber.transcribe(tmp_path)
    except Exception as e:
        logger.error("Transcription failed: %s", e)
        await status_msg.edit_text("Не удалось распознать голосовое. Попробуй ещё раз или напиши текстом.")
        return
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not text.strip():
        await status_msg.edit_text("Не удалось распознать речь. Попробуй ещё раз.")
        return

    await state.update_data(voice_pending_dump=text)
    await status_msg.edit_text(
        f"🎙 _{text}_\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=voice_confirm_kb("dump"),
    )


@router.callback_query(DumpStates.waiting_dump, F.data == "vc_ok:dump")
async def confirm_voice_dump(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    text = data.get("voice_pending_dump", "")
    if not text:
        await callback.answer("Текст не найден", show_alert=True)
        return
    await callback.answer()  # must answer before LLM call in _process_dump
    await callback.message.delete()
    await _process_dump(callback.message, state, db, user_db, text, is_voice=True)


@router.callback_query(DumpStates.waiting_dump, F.data == "vc_edit:dump")
async def edit_voice_dump(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "✏️ Напиши текстом — что хочешь разобрать:"
    )
    await callback.answer()


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
        await message.answer("У тебя уже есть выгрузка на сегодня. Задачи можно посмотреть через 📋 Задачи.")
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
    menu_texts = {
        "🧠 Выгрузка", "📌 Контекст", "📋 Задачи", "⚙️ Настройки",
        "🧠 Dump", "🎯 Фокус дня", "📅 Фокус недели", "🗓 Фокус месяца",
    }
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
            "У тебя уже есть выгрузка на сегодня. Задачи можно посмотреть через 📋 Задачи."
        )
        await state.clear()
        return

    await message.answer("🤔 Анализирую...")

    weekly_focus, monthly_focus = await _get_focuses(db, user_db.id)
    weekly_context, monthly_context = await _get_contexts(db, user_db.id)

    analysis = await coach.analyze_mind_dump(
        text=text,
        weekly_focus=weekly_focus,
        monthly_focus=monthly_focus,
        tone=user_db.tone,
        spheres=", ".join(s.name for s in user_db.spheres) if user_db.spheres else "",
        weekly_context=weekly_context,
        monthly_context=monthly_context,
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
        session_obj.household_tasks = {"tasks": analysis.tasks}
        session_obj.llm_response_json = analysis.raw
        session_obj.accepted_at = datetime.now(ZoneInfo(user_db.tz_personal or "Europe/Moscow"))
    else:
        session_obj = DailySession(
            user_id=user_db.id,
            date_local=today,
            dump_text=text,
            is_voice=is_voice,
            energy=analysis.suggested_energy,
            household_tasks={"tasks": analysis.tasks},
            llm_response_json=analysis.raw,
            accepted_at=datetime.now(ZoneInfo(user_db.tz_personal or "Europe/Moscow")),
        )
        db.add(session_obj)

    await db.commit()
    await db.refresh(session_obj)

    await log_event(db, "dump_created", user_id=user_db.id, metadata={
        "is_voice": is_voice, "session_id": session_obj.id
    })

    formatted = _format_analysis(analysis)
    await message.answer(formatted or "Я записала выгрузку.", parse_mode="Markdown")

    carried_result = await db.execute(
        select(TodoItem).where(
            TodoItem.user_id == user_db.id,
            TodoItem.date_local <= today,
            TodoItem.status == "pending",
            TodoItem.session_id.is_(None),
        )
    )
    carried_items = list(carried_result.scalars().all())
    if carried_items:
        carried_text = "\n".join(f"  • {item.text}" for item in carried_items)
        await message.answer(
            "Есть открытые задачи с прошлых дней:\n"
            f"{carried_text}\n\n"
            "Добавить их в список на сегодня?",
            reply_markup=carried_tasks_kb(session_obj.id),
        )

    task_count = len(analysis.tasks)
    if task_count:
        await message.answer(
            f"Нашла задач: {task_count}. Добавить их в список на сегодня?",
            reply_markup=tasks_review_kb(session_obj.id, has_tasks=True),
        )
    else:
        await message.answer(
            "Я не увидела явных задач. Можно добавить вручную, если что-то появилось.",
            reply_markup=tasks_review_kb(session_obj.id, has_tasks=False),
        )
    await state.clear()
