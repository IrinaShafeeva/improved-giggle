"""Handler for /start — entry point."""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.handlers.profile import ask_profile_onboarding
from bot.keyboards.inline import main_menu_kb
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
            "Ты уже в «Моем дне». Отправь голосовое или текст для утренней выгрузки, "
            "или используй меню ниже.",
            reply_markup=main_menu_kb(),
        )
        return

    await log_event(db, "start", user_id=user_db.id)

    await message.answer(
        "Привет! 👋\n\n"
        "Я помогу каждый день выгружать мысли, отделять фон от реальных дел "
        "и выбирать один посильный следующий шаг.\n\n"
        "Начнём с живого профиля — без анкеты.",
    )
    await ask_profile_onboarding(message, state)
