"""Bot entry point — python -m bot"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.handlers import get_all_routers
from bot.middlewares.db import DbSessionMiddleware
from bot.services.scheduler_service import scheduler, set_bot, rebuild_schedules
from bot.db.session import engine
from bot.db.base import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    """Run on bot startup."""
    # Drop all and recreate (safe while only dev user in DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables recreated")

    # Set bot reference for scheduler
    set_bot(bot)

    # Rebuild scheduled jobs from DB
    await rebuild_schedules()

    # Start scheduler
    scheduler.start()
    logger.info("Scheduler started")

    me = await bot.get_me()
    logger.info("Bot started: @%s", me.username)


async def on_shutdown(bot: Bot) -> None:
    """Run on bot shutdown."""
    scheduler.shutdown(wait=False)
    await engine.dispose()
    logger.info("Bot stopped")


async def main() -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Register middleware
    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())

    # Register routers
    for router in get_all_routers():
        dp.include_router(router)

    # Lifecycle hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Start polling
    logger.info("Starting bot polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
