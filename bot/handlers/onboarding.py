"""Onboarding flow — multi-step setup after /start."""

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.db.models import User, Focus
from bot.keyboards.inline import (
    spheres_kb,
    tone_kb,
    time_picker_kb,
    main_menu_kb,
)
from bot.states.fsm import OnboardingStates
from bot.utils.analytics import log_event

router = Router()


# ── Step 1: Spheres ────────────────────────────────────────────────────────────

@router.callback_query(OnboardingStates.choosing_spheres, F.data.startswith("sphere:"))
async def on_sphere_toggle(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    sphere = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected: set = data.get("selected_spheres", set())

    if sphere in selected:
        selected.discard(sphere)
    else:
        selected.add(sphere)

    await state.update_data(selected_spheres=selected)
    await callback.message.edit_reply_markup(reply_markup=spheres_kb(selected))
    await callback.answer()


@router.callback_query(OnboardingStates.choosing_spheres, F.data == "spheres_done")
async def on_spheres_done(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    data = await state.get_data()
    selected: set = data.get("selected_spheres", set())

    if len(selected) < 3:
        await callback.answer("Выбери минимум 3 сферы", show_alert=True)
        return

    user_db.spheres = ",".join(sorted(selected))
    await db.commit()

    await callback.message.edit_text(
        "Отлично! Теперь напиши свой фокус на эту неделю.\n\n"
        "Что самое важное ты хочешь продвинуть за эту неделю? "
        "(одно предложение)"
    )
    await state.set_state(OnboardingStates.entering_weekly_focus)
    await callback.answer()


# ── Step 2: Weekly focus ───────────────────────────────────────────────────────

@router.message(OnboardingStates.entering_weekly_focus, F.text)
async def on_weekly_focus(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    focus_text = message.text.strip()
    if len(focus_text) < 3:
        await message.answer("Слишком коротко. Напиши хотя бы одно предложение.")
        return

    # Upsert weekly focus
    result = await db.execute(
        select(Focus).where(Focus.user_id == user_db.id, Focus.period == "week")
    )
    focus = result.scalar_one_or_none()
    if focus:
        focus.text = focus_text
    else:
        focus = Focus(user_id=user_db.id, period="week", text=focus_text)
        db.add(focus)
    await db.commit()

    await message.answer(
        "👍 Записал.\n\n"
        "Теперь фокус на месяц — какой главный результат ты хочешь "
        "к концу месяца? (одно предложение)"
    )
    await state.set_state(OnboardingStates.entering_monthly_focus)


# ── Step 3: Monthly focus ──────────────────────────────────────────────────────

@router.message(OnboardingStates.entering_monthly_focus, F.text)
async def on_monthly_focus(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    focus_text = message.text.strip()
    if len(focus_text) < 3:
        await message.answer("Слишком коротко. Напиши хотя бы одно предложение.")
        return

    result = await db.execute(
        select(Focus).where(Focus.user_id == user_db.id, Focus.period == "month")
    )
    focus = result.scalar_one_or_none()
    if focus:
        focus.text = focus_text
    else:
        focus = Focus(user_id=user_db.id, period="month", text=focus_text)
        db.add(focus)
    await db.commit()

    await message.answer(
        "Отлично! Выбери тон, в котором я буду с тобой общаться:",
        reply_markup=tone_kb(),
    )
    await state.set_state(OnboardingStates.choosing_tone)


# ── Step 4: Tone ───────────────────────────────────────────────────────────────

@router.callback_query(OnboardingStates.choosing_tone, F.data.startswith("tone:"))
async def on_tone_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    tone = callback.data.split(":", 1)[1]
    user_db.tone = tone
    await db.commit()

    await callback.message.edit_text(
        "🌅 В какое время тебе удобно получать утренний пинг для mind dump?",
        reply_markup=time_picker_kb("morning"),
    )
    await state.set_state(OnboardingStates.choosing_morning_time)
    await callback.answer()


# ── Step 5: Morning time ──────────────────────────────────────────────────────

@router.callback_query(
    OnboardingStates.choosing_morning_time, F.data.startswith("morning_time:")
)
async def on_morning_time(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    time_str = callback.data.split(":", 1)[1]
    user_db.morning_ping_time = time_str
    await db.commit()

    await callback.message.edit_text(
        "🌙 В какое время вечером напомнить о закрытии дня?",
        reply_markup=time_picker_kb("evening"),
    )
    await state.set_state(OnboardingStates.choosing_evening_time)
    await callback.answer()


# ── Step 6: Evening time → onboarding complete ────────────────────────────────

@router.callback_query(
    OnboardingStates.choosing_evening_time, F.data.startswith("evening_time:")
)
async def on_evening_time(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    time_str = callback.data.split(":", 1)[1]
    user_db.evening_report_time = time_str
    user_db.onboarding_complete = True
    await db.commit()

    await log_event(db, "onboarding_complete", user_id=user_db.id)

    await callback.message.edit_text(
        "✅ Настройка завершена!\n\n"
        f"Утренний пинг: {user_db.morning_ping_time}\n"
        f"Вечерний отчёт: {user_db.evening_report_time}\n"
        f"Тон: {user_db.tone}\n\n"
        "Ты можешь сделать mind dump прямо сейчас — "
        "отправь голосовое или текст.\n"
        "Или дождись утреннего пинга. Поехали! 🚀"
    )
    await callback.message.answer(
        "Главное меню:", reply_markup=main_menu_kb()
    )
    await state.clear()
    await callback.answer()
