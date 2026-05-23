"""Handler for /start — entry point."""

from aiogram import Router
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
            "Ты уже в «Моем дне». Отправь голосовое или текст для утренней выгрузки, "
            "или используй меню ниже.",
            reply_markup=main_menu_kb(),
        )
        return

    await log_event(db, "start", user_id=user_db.id)

    await message.answer(
        "Привет! 👋\n\n"
        "Я помогу тебе каждый день выгружать мысли, видеть чувства, контекст и задачи без терапевтической воды.\n\n"
        "💡 На большинство вопросов можно отвечать голосом — просто отправь голосовое.\n\n"
        "Начнём с карты твоей реальности.\n"
        "Выбери 3–6 сфер жизни, которые для тебя важны сейчас.\n"
        "Можешь добавить свою через «➕ Своя сфера».\n\n"
        "Нажми на сферы и потом «Готово»:",
        parse_mode="Markdown",
        reply_markup=spheres_kb(),
    )
    await state.set_state(OnboardingStates.choosing_spheres)
    await state.update_data(selected_spheres=[])
