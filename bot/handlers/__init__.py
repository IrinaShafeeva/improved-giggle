from aiogram import Router

from bot.handlers.start import router as start_router
from bot.handlers.onboarding import router as onboarding_router
from bot.handlers.dump import router as dump_router
from bot.handlers.focus import router as focus_router
from bot.handlers.checkin import router as checkin_router
from bot.handlers.evening import router as evening_router
from bot.handlers.deeper import router as deeper_router
from bot.handlers.settings import router as settings_router
from bot.handlers.todos import router as todos_router


def get_all_routers() -> list[Router]:
    """Order matters: specific handlers first, catch-all (dump) last."""
    return [
        start_router,
        onboarding_router,
        focus_router,
        todos_router,        # todo input state + item callbacks
        checkin_router,
        evening_router,
        deeper_router,
        settings_router,    # must be before dump (has menu button handlers)
        dump_router,         # has catch-all voice/text handlers — keep last
    ]
