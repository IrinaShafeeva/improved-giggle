"""Bot entry point — python -m bot"""

import asyncio
import logging
import os

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

# Webhook path uses the bot token as a secret segment
_WEBHOOK_PATH = f"/webhook/{settings.bot_token}"


async def on_startup(bot: Bot) -> None:
    """Run on bot startup."""
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")

    # Set webhook if running on Render (RENDER_EXTERNAL_URL is set automatically)
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if render_url:
        webhook_url = f"{render_url}{_WEBHOOK_PATH}"
        await bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info("Webhook set: %s", webhook_url)
    else:
        # Local dev: make sure no stale webhook is registered
        await bot.delete_webhook(drop_pending_updates=True)

    set_bot(bot)
    await rebuild_schedules()
    scheduler.start()
    logger.info("Scheduler started")

    me = await bot.get_me()
    logger.info("Bot started: @%s", me.username)


async def on_shutdown(bot: Bot) -> None:
    """Run on bot shutdown."""
    render_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if render_url:
        await bot.delete_webhook()
    scheduler.shutdown(wait=False)
    await engine.dispose()
    logger.info("Bot stopped")


def _build_dp() -> tuple[Bot, Dispatcher]:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    for router in get_all_routers():
        dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    return bot, dp


async def main() -> None:
    bot, dp = _build_dp()

    render_url = os.getenv("RENDER_EXTERNAL_URL", "")

    if render_url:
        # ── Production on Render: webhook mode ────────────────────────────────
        from aiohttp import web
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

        port = int(os.getenv("PORT", 8080))
        logger.info("Starting webhook server on port %d (Render mode)...", port)

        app = web.Application()
        # Health-check endpoint (required for Render web service)
        app.router.add_get("/health", lambda _r: web.Response(text="OK"))

        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=_WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

        # Keep alive until process is killed
        await asyncio.Event().wait()
    else:
        # ── Local dev: polling mode ────────────────────────────────────────────
        logger.info("Starting bot polling (local dev)...")
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
