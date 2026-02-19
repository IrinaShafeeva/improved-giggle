"""Scheduler service — APScheduler jobs for pings, checkins, evening reminders."""

from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from bot.db.models import User, DailySession
from bot.db.session import async_session

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Will be set from __main__.py after bot is created
_bot = None


def set_bot(bot) -> None:
    global _bot
    _bot = bot


# ── Morning ping ──────────────────────────────────────────────────────────────

async def send_morning_ping(user_tg_id: int) -> None:
    """Send morning mind dump prompt."""
    if _bot is None:
        logger.error("Bot not set in scheduler")
        return

    from bot.keyboards.inline import morning_ping_kb

    try:
        await _bot.send_message(
            chat_id=user_tg_id,
            text="☀️ Доброе утро!\n\nХочешь сделать mind dump? "
                 "Отправь голосовое или текст — выгрузи всё, что в голове.",
            reply_markup=morning_ping_kb(),
        )
    except Exception as e:
        logger.error("Failed to send morning ping to %s: %s", user_tg_id, e)


# ── Checkin notifications ──────────────────────────────────────────────────────

async def send_checkin(user_tg_id: int, session_id: int, kind: str) -> None:
    """Send +3h or +6h checkin notification."""
    if _bot is None:
        return

    from bot.keyboards.inline import checkin_kb

    hour_label = "3 часа" if kind == "t3" else "6 часов"

    try:
        await _bot.send_message(
            chat_id=user_tg_id,
            text=f"⏰ Прошло {hour_label} с начала фокуса.\n\n"
                 "Как продвигается?",
            reply_markup=checkin_kb(session_id, kind),
        )
    except Exception as e:
        logger.error("Failed to send checkin to %s: %s", user_tg_id, e)


# ── Evening report notification ────────────────────────────────────────────────

async def send_evening_reminder(user_tg_id: int, session_id: int, attempt: int = 1) -> None:
    """Send evening report prompt. attempt=1 first, 2/3 for reminders."""
    if _bot is None:
        return

    from bot.keyboards.inline import evening_status_kb

    if attempt == 1:
        text = (
            "🌙 Время закрыть день!\n\n"
            "Как прошёл день? Выбери статус:"
        )
    elif attempt == 2:
        text = "⏰ Напоминаю — закрой день, пока свежо в памяти."
    else:
        text = "🔔 Последнее напоминание — закрой день!"

    try:
        await _bot.send_message(
            chat_id=user_tg_id,
            text=text,
            reply_markup=evening_status_kb(session_id),
        )
    except Exception as e:
        logger.error("Failed to send evening reminder to %s: %s", user_tg_id, e)


# ── Schedule checkins for a specific session ───────────────────────────────────

async def schedule_checkins(
    user: User,
    session: DailySession,
    accepted_at: datetime,
) -> None:
    """Schedule +3h and +6h checkin jobs for a daily session."""
    tz = ZoneInfo(user.tz_personal or "Europe/Moscow")

    t3 = accepted_at + timedelta(hours=3)
    t6 = accepted_at + timedelta(hours=6)

    job_id_t3 = f"checkin_{session.id}_t3"
    job_id_t6 = f"checkin_{session.id}_t6"

    # Remove existing jobs if any (e.g. re-scheduling)
    for jid in (job_id_t3, job_id_t6):
        existing = scheduler.get_job(jid)
        if existing:
            existing.remove()

    scheduler.add_job(
        send_checkin,
        trigger=DateTrigger(run_date=t3),
        args=[user.tg_id, session.id, "t3"],
        id=job_id_t3,
        replace_existing=True,
    )
    scheduler.add_job(
        send_checkin,
        trigger=DateTrigger(run_date=t6),
        args=[user.tg_id, session.id, "t6"],
        id=job_id_t6,
        replace_existing=True,
    )
    logger.info("Scheduled checkins for session %s at %s and %s", session.id, t3, t6)


# ── Schedule evening reminders ─────────────────────────────────────────────────

def schedule_evening_reminders(
    user: User,
    session: DailySession,
) -> None:
    """Schedule evening report reminder + 2 follow-ups."""
    if not user.evening_report_time:
        return

    tz = ZoneInfo(user.tz_personal or "Europe/Moscow")
    h, m = map(int, user.evening_report_time.split(":"))
    today = datetime.now(tz).date()
    evening_dt = datetime.combine(today, dt_time(h, m), tzinfo=tz)

    # If already past, skip
    if evening_dt < datetime.now(tz):
        return

    base_id = f"evening_{session.id}"

    scheduler.add_job(
        send_evening_reminder,
        trigger=DateTrigger(run_date=evening_dt),
        args=[user.tg_id, session.id, 1],
        id=f"{base_id}_1",
        replace_existing=True,
    )
    scheduler.add_job(
        send_evening_reminder,
        trigger=DateTrigger(run_date=evening_dt + timedelta(minutes=30)),
        args=[user.tg_id, session.id, 2],
        id=f"{base_id}_2",
        replace_existing=True,
    )
    scheduler.add_job(
        send_evening_reminder,
        trigger=DateTrigger(run_date=evening_dt + timedelta(minutes=90)),
        args=[user.tg_id, session.id, 3],
        id=f"{base_id}_3",
        replace_existing=True,
    )
    logger.info("Scheduled evening reminders for session %s at %s", session.id, evening_dt)


# ── Rebuild all scheduled jobs from DB on startup ──────────────────────────────

async def rebuild_schedules() -> None:
    """Rebuild scheduler jobs from DB after restart."""
    async with async_session() as db:
        # Morning pings for all active users
        result = await db.execute(
            select(User).where(
                User.onboarding_complete.is_(True),
                User.morning_ping_time.isnot(None),
            )
        )
        users = result.scalars().all()

        for user in users:
            h, m = map(int, user.morning_ping_time.split(":"))
            tz = ZoneInfo(user.tz_personal or "Europe/Moscow")

            job_id = f"morning_ping_{user.id}"
            scheduler.add_job(
                send_morning_ping,
                trigger=CronTrigger(hour=h, minute=m, timezone=tz),
                args=[user.tg_id],
                id=job_id,
                replace_existing=True,
            )

        logger.info("Rebuilt morning pings for %d users", len(users))

        # Rebuild checkins and evening reminders for TODAY's active sessions only
        from datetime import timezone
        today_utc = datetime.now(timezone.utc).date()
        today_sessions = await db.execute(
            select(DailySession).where(
                DailySession.accepted_at.isnot(None),
                DailySession.date_local == today_utc,
            )
        )
        for session in today_sessions.scalars().all():
            user_result = await db.execute(
                select(User).where(User.id == session.user_id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                continue

            tz = ZoneInfo(user.tz_personal or "Europe/Moscow")
            now = datetime.now(tz)

            if session.accepted_at:
                # Only schedule future checkins
                t3 = session.accepted_at + timedelta(hours=3)
                t6 = session.accepted_at + timedelta(hours=6)

                if t3 > now:
                    scheduler.add_job(
                        send_checkin,
                        trigger=DateTrigger(run_date=t3),
                        args=[user.tg_id, session.id, "t3"],
                        id=f"checkin_{session.id}_t3",
                        replace_existing=True,
                    )
                if t6 > now:
                    scheduler.add_job(
                        send_checkin,
                        trigger=DateTrigger(run_date=t6),
                        args=[user.tg_id, session.id, "t6"],
                        id=f"checkin_{session.id}_t6",
                        replace_existing=True,
                    )

            # Evening reminders
            schedule_evening_reminders(user, session)

        logger.info("Rebuilt session schedules")
