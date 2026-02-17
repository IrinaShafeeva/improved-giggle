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


def _col_exists(conn, table: str, column: str) -> bool:
    from sqlalchemy import text
    r = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return r.fetchone() is not None


def _apply_schema_updates(conn) -> None:
    """Add columns that create_all can't add to existing tables."""
    from sqlalchemy import text

    # focuses: new columns for smart onboarding
    focus_cols = {
        "sphere_id": "INTEGER REFERENCES spheres(id) ON DELETE SET NULL",
        "meaning": "TEXT",
        "metric": "TEXT",
        "cost": "TEXT",
        "llm_score": "VARCHAR(20)",
        "llm_reframe": "TEXT",
        "is_active": "BOOLEAN DEFAULT TRUE",
        "week_number": "INTEGER",
        "updated_at": "TIMESTAMPTZ DEFAULT NOW()",
    }
    for col, typedef in focus_cols.items():
        if not _col_exists(conn, "focuses", col):
            conn.execute(text(f"ALTER TABLE focuses ADD COLUMN {col} {typedef}"))
            logger.info("Added focuses.%s", col)

    # daily_sessions: new columns
    ds_cols = {
        "household_tasks": "JSONB",
        "step_bank_id": "INTEGER REFERENCES step_bank(id) ON DELETE SET NULL",
    }
    for col, typedef in ds_cols.items():
        if not _col_exists(conn, "daily_sessions", col):
            conn.execute(text(f"ALTER TABLE daily_sessions ADD COLUMN {col} {typedef}"))
            logger.info("Added daily_sessions.%s", col)

    # users: drop old spheres text column if it exists
    if _col_exists(conn, "users", "spheres"):
        conn.execute(text("ALTER TABLE users DROP COLUMN spheres"))
        logger.info("Dropped users.spheres (migrated to spheres table)")


async def on_startup(bot: Bot) -> None:
    """Run on bot startup."""
    # Create new tables + migrate existing schema
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_schema_updates)
    logger.info("Database tables ensured")

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
