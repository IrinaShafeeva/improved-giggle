"""Handler for /start — entry point."""

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.keyboards.inline import main_menu_kb, spheres_kb
from bot.states.fsm import OnboardingStates
from bot.utils.analytics import log_event

router = Router()


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    db: AsyncSession,
    user_db: User,
) -> None:
    if user_db.onboarding_complete:
        await message.answer(
            f"Привет, {user_db.first_name}! 👋\n\n"
            "Ты уже в системе. Отправь голосовое или текст для mind dump, "
            "или используй меню ниже.",
            reply_markup=main_menu_kb(),
        )
        return

    await log_event(db, "start", user_id=user_db.id)

    await message.answer(
        "Привет! 👋 Я — Mastermind Coach.\n\n"
        "Я помогу тебе каждый день структурировать мысли, "
        "выбрать фокус и довести дело до конца.\n\n"
        "Давай настроим бота под тебя. Начнём с выбора сфер жизни, "
        "которые для тебя сейчас важны.\n\n"
        "Выбери 3–6 сфер и нажми «Готово»:",
        reply_markup=spheres_kb(),
    )
    await state.set_state(OnboardingStates.choosing_spheres)
    await state.update_data(selected_spheres=set())
