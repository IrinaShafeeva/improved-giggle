"""Daily todo checklist handler — simple tasks without coaching."""

from __future__ import annotations

import logging
import tempfile
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, TodoItem, DailySession
from bot.keyboards.inline import todo_input_kb, todo_list_kb, main_menu_kb, voice_confirm_kb
from bot.services.transcriber import transcriber
from bot.states.fsm import FocusStates

logger = logging.getLogger(__name__)

router = Router()


def _user_today(user: User) -> date:
    tz = ZoneInfo(user.tz_personal or "Europe/Moscow")
    from datetime import datetime
    return datetime.now(tz).date()


async def _transcribe_voice(message: Message, bot: Bot) -> str | None:
    file = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await bot.download_file(file.file_path, tmp_path)
    try:
        text = await transcriber.transcribe(tmp_path)
        return text.strip() or None
    except Exception as e:
        logger.error("Todo transcription failed: %s", e)
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _parse_todo_lines(raw: str) -> list[str]:
    """Split user input into individual todo items by comma or newline."""
    items = []
    for chunk in raw.replace(",", "\n").splitlines():
        item = chunk.strip().strip("•-–").strip()
        if item:
            items.append(item)
    return items[:10]  # max 10 per day


async def _save_todos(
    db: AsyncSession,
    user_db: User,
    session_id: int | None,
    texts: list[str],
    today: date,
    carried_from_ids: list[int] | None = None,
) -> list[TodoItem]:
    todos = []
    for i, text in enumerate(texts):
        carried_from = carried_from_ids[i] if carried_from_ids else None
        item = TodoItem(
            user_id=user_db.id,
            session_id=session_id,
            date_local=today,
            text=text,
            status="pending",
            carried_from_id=carried_from,
        )
        db.add(item)
        todos.append(item)
    await db.commit()
    for item in todos:
        await db.refresh(item)
    return todos


async def _get_pending_todos(
    db: AsyncSession, user_id: int, session_id: int | None
) -> list[TodoItem]:
    result = await db.execute(
        select(TodoItem).where(
            TodoItem.user_id == user_id,
            TodoItem.session_id == session_id,
            TodoItem.status == "pending",
        )
    )
    return list(result.scalars().all())


async def _get_pending_todos_for_date(
    db: AsyncSession, user_id: int, today: date
) -> list[TodoItem]:
    result = await db.execute(
        select(TodoItem).where(
            TodoItem.user_id == user_id,
            TodoItem.date_local == today,
            TodoItem.status == "pending",
        )
    )
    return list(result.scalars().all())


def _format_todos_message(todos: list[TodoItem]) -> str:
    lines = ["📋 *Дела на сегодня:*"]
    for t in todos:
        lines.append(f"• {t.text}")
    return "\n".join(lines)


def _session_tasks(session: DailySession) -> list[str]:
    if session.household_tasks and isinstance(session.household_tasks, dict):
        tasks = session.household_tasks.get("tasks", [])
        if isinstance(tasks, list):
            return [str(t).strip() for t in tasks if str(t).strip()]
    if session.llm_response_json and isinstance(session.llm_response_json, dict):
        tasks = session.llm_response_json.get("tasks", [])
        if isinstance(tasks, list):
            return [str(t).strip() for t in tasks if str(t).strip()]
    return []


@router.message(F.text == "📋 Задачи")
async def tasks_button(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    if not user_db.onboarding_complete:
        await message.answer("Сначала пройди настройку: /start")
        return
    today = _user_today(user_db)
    todos = await _get_pending_todos_for_date(db, user_db.id, today)
    if todos:
        await message.answer(
            _format_todos_message(todos),
            parse_mode="Markdown",
            reply_markup=todo_list_kb(todos),
        )
    else:
        await state.set_state(FocusStates.entering_todos)
        await state.update_data(session_id=None)
        await message.answer(
            "На сегодня нет открытых задач. Напиши или наговори новую задачу.",
            reply_markup=todo_input_kb(),
        )


# ── Todo input after focus confirmed ──────────────────────────────────────────

async def _finish_todos(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    """Finalize todo collection and show main menu."""
    data = await state.get_data()
    session_id = data.get("session_id")
    today = _user_today(user_db)

    # Show final todo list if any were saved
    todos = await _get_pending_todos(db, user_db.id, session_id)
    if todos:
        await message.answer(
            _format_todos_message(todos) + "\n\nВсё записала! Буду напоминать.",
            parse_mode="Markdown",
        )
    await message.answer("Главное меню:", reply_markup=main_menu_kb())
    await state.clear()


@router.message(FocusStates.entering_todos, F.text)
async def on_todo_text(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    raw = message.text.strip()
    items = _parse_todo_lines(raw)
    if not items:
        await message.answer("Не разобрала. Напиши или скажи список дел, или нажми «Пропустить».")
        return

    data = await state.get_data()
    session_id = data.get("session_id")
    today = _user_today(user_db)
    await _save_todos(db, user_db, session_id, items, today)
    await _finish_todos(message, state, db, user_db)


@router.message(FocusStates.entering_todos, F.voice)
async def on_todo_voice(
    message: Message,
    bot: Bot,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    text = await _transcribe_voice(message, bot)
    if not text:
        await message.answer("Не удалось распознать. Напиши текстом или нажми «Пропустить».")
        return
    await state.update_data(voice_pending_todos=text)
    await message.answer(
        f"🎙 _{text}_\n\nВсё верно?",
        parse_mode="Markdown",
        reply_markup=voice_confirm_kb("todos"),
    )


@router.callback_query(FocusStates.entering_todos, F.data == "vc_ok:todos")
async def confirm_voice_todos(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession, user_db: User,
) -> None:
    data = await state.get_data()
    text = data.get("voice_pending_todos", "")
    if not text:
        await callback.answer("Текст не найден", show_alert=True)
        return

    items = _parse_todo_lines(text)
    if not items:
        await callback.message.edit_text(
            "Не разобрала. Напиши список дел или нажми «Пропустить».",
            reply_markup=todo_input_kb(),
        )
        await callback.answer()
        return

    await callback.answer()
    await callback.message.delete()
    session_id = data.get("session_id")
    today = _user_today(user_db)
    await _save_todos(db, user_db, session_id, items, today)
    await _finish_todos(callback.message, state, db, user_db)


@router.callback_query(FocusStates.entering_todos, F.data == "vc_edit:todos")
async def edit_voice_todos(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "✏️ Напиши исправленный список дел:",
        reply_markup=todo_input_kb(),
    )
    await callback.answer()


@router.callback_query(FocusStates.entering_todos, F.data == "todo_skip")
async def on_todo_skip(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.message.edit_text("Ок, без списка дел. Поехали! 🚀")
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith("tasks:add_all:"))
async def on_tasks_add_all(
    callback: CallbackQuery,
    db: AsyncSession,
    user_db: User,
) -> None:
    session_id = int(callback.data.split(":")[2])
    result = await db.execute(
        select(DailySession).where(
            DailySession.id == session_id,
            DailySession.user_id == user_db.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        await callback.answer("Сессия не найдена", show_alert=True)
        return

    tasks = _session_tasks(session)
    if not tasks:
        await callback.answer("Задачи не найдены", show_alert=True)
        return

    today = _user_today(user_db)
    existing = await _get_pending_todos(db, user_db.id, session_id)
    existing_texts = {t.text.strip().lower() for t in existing}
    new_tasks = [t for t in tasks if t.strip().lower() not in existing_texts]
    if new_tasks:
        await _save_todos(db, user_db, session_id, new_tasks, today)

    todos = await _get_pending_todos(db, user_db.id, session_id)
    await callback.message.edit_text(
        _format_todos_message(todos) if todos else "Задач нет.",
        parse_mode="Markdown",
        reply_markup=todo_list_kb(todos) if todos else None,
    )
    await callback.answer("Добавлено")


@router.callback_query(F.data.startswith("tasks:add_one:"))
async def on_tasks_add_one(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    session_id = int(callback.data.split(":")[2])
    await state.set_state(FocusStates.entering_todos)
    await state.update_data(session_id=session_id)
    await callback.message.answer("Напиши или наговори задачу. Можно несколько через запятую или с новой строки.")
    await callback.answer()


@router.callback_query(F.data.startswith("tasks:skip:"))
async def on_tasks_skip(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Ок, задачи не добавляю.")
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("carried:add_all:"))
async def on_carried_add_all(
    callback: CallbackQuery,
    db: AsyncSession,
    user_db: User,
) -> None:
    session_id = int(callback.data.split(":")[2])
    today = _user_today(user_db)
    result = await db.execute(
        select(TodoItem).where(
            TodoItem.user_id == user_db.id,
            TodoItem.date_local <= today,
            TodoItem.status == "pending",
            TodoItem.session_id.is_(None),
        )
    )
    carried_items = list(result.scalars().all())
    for item in carried_items:
        item.session_id = session_id
        item.date_local = today
    await db.commit()

    todos = await _get_pending_todos(db, user_db.id, session_id)
    await callback.message.edit_text(
        _format_todos_message(todos) if todos else "Хвостов не осталось.",
        parse_mode="Markdown",
        reply_markup=todo_list_kb(todos) if todos else None,
    )
    await callback.answer("Хвосты добавлены")


@router.callback_query(F.data.startswith("carried:skip:"))
async def on_carried_skip(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Ок, хвосты пока не добавляю.")
    await callback.answer()


@router.callback_query(F.data.startswith("todo:add"))
async def on_todo_add(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    parts = callback.data.split(":")
    session_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    await state.set_state(FocusStates.entering_todos)
    await state.update_data(session_id=session_id)
    await callback.message.answer("Напиши или наговори новую задачу.")
    await callback.answer()


# ── Todo item actions (from checkin messages) ─────────────────────────────────

@router.callback_query(F.data.startswith("todo:done:"))
async def on_todo_done(
    callback: CallbackQuery,
    db: AsyncSession,
    user_db: User,
) -> None:
    todo_id = int(callback.data.split(":")[2])
    result = await db.execute(
        select(TodoItem).where(TodoItem.id == todo_id, TodoItem.user_id == user_db.id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        await callback.answer("Задача не найдена", show_alert=True)
        return

    todo.status = "done"
    await db.commit()
    await callback.answer("✅ Отмечено!")

    # Refresh remaining todos and update message
    session_id = todo.session_id
    remaining = await _get_pending_todos(db, user_db.id, session_id)
    if remaining:
        await callback.message.edit_text(
            _format_todos_message(remaining),
            parse_mode="Markdown",
            reply_markup=todo_list_kb(remaining),
        )
    else:
        await callback.message.edit_text("✅ Все дела на сегодня сделаны!")


@router.callback_query(F.data.startswith("todo:carry:"))
async def on_todo_carry(
    callback: CallbackQuery,
    db: AsyncSession,
    user_db: User,
) -> None:
    todo_id = int(callback.data.split(":")[2])
    result = await db.execute(
        select(TodoItem).where(TodoItem.id == todo_id, TodoItem.user_id == user_db.id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        await callback.answer("Задача не найдена", show_alert=True)
        return

    # Mark original as carried over
    todo.status = "carried_over"

    # Create new item for tomorrow (no session_id yet — will be attached when user does dump)
    tz = ZoneInfo(user_db.tz_personal or "Europe/Moscow")
    from datetime import datetime
    tomorrow = datetime.now(tz).date() + timedelta(days=1)
    new_item = TodoItem(
        user_id=user_db.id,
        session_id=None,
        date_local=tomorrow,
        text=todo.text,
        status="pending",
        carried_from_id=todo.id,
    )
    db.add(new_item)
    await db.commit()
    await callback.answer("➡️ Перенесено на завтра")

    # Refresh remaining todos
    session_id = todo.session_id
    remaining = await _get_pending_todos(db, user_db.id, session_id)
    if remaining:
        await callback.message.edit_text(
            _format_todos_message(remaining),
            parse_mode="Markdown",
            reply_markup=todo_list_kb(remaining),
        )
    else:
        await callback.message.edit_text("📋 Все дела перенесены или закрыты.")
