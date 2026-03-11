"""
ZBS CRM Bot — Main Entry Point
Telegram bot for managing content, clients, tasks, and finances

ENV VARIABLES REQUIRED:
  BOT_TOKEN         — Telegram bot token from @BotFather
  DATABASE_URL      — PostgreSQL connection string
  ADMIN_IDS         — Comma-separated Telegram IDs of admins (Robert, Susanna)
  
OPTIONAL:
  TZ                — Timezone (default: Asia/Tashkent)
"""

import os
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from database import init_db, seed_defaults
from seed import seed as seed_data
from handlers import (
    common_router, fallback_router, schedule_router, crm_router,
    finance_router, report_router, bloggers_router
)
from handlers.common import ADMIN_IDS
from handlers.report import (
    send_morning_report, send_morning_reminders, 
    send_day_before_reminders, send_hourly_reminders, send_overdue_alerts
)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("zbs_crm")

# Config
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TIMEZONE = os.environ.get("TZ", "Asia/Tashkent")
tz = pytz.timezone(TIMEZONE)


async def on_startup(bot: Bot):
    """Run on bot startup"""
    logger.info("🚀 Starting ZBS CRM Bot...")
    
    # Init database
    await init_db()
    
    # Seed initial data (team, projects, clients, deals)
    try:
        await seed_data()
    except Exception as e:
        logger.info(f"Seed skipped (probably already done): {e}")
    
    # Populate admin IDs
    admin_ids_str = os.environ.get("ADMIN_IDS", "")
    for id_str in admin_ids_str.split(","):
        id_str = id_str.strip()
        if id_str:
            ADMIN_IDS.add(int(id_str))
    logger.info(f"👑 Admin IDs: {ADMIN_IDS}")
    
    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "✅ <b>ZBS CRM Bot запущен!</b>\n\n"
                f"⏰ {datetime.now(tz).strftime('%d.%m.%Y %H:%M')}\n"
                "Напиши /start для начала работы.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    logger.info("✅ Bot started successfully")


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is required!")
    
    # Init bot & dispatcher
    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True
        )
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Register routers (order matters — fallback must be LAST)
    dp.include_router(common_router)
    dp.include_router(schedule_router)
    dp.include_router(crm_router)
    dp.include_router(finance_router)
    dp.include_router(report_router)
    dp.include_router(bloggers_router)
    dp.include_router(fallback_router)  # catches unhandled messages
    
    # Setup scheduler
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    
    # Morning report at 9:00 Tashkent
    scheduler.add_job(
        send_morning_report,
        CronTrigger(hour=9, minute=0, timezone=TIMEZONE),
        args=[bot],
        id="morning_report",
        name="Morning Daily Report"
    )
    
    # Morning reminders at 10:00 (today's tasks to assignees)
    scheduler.add_job(
        send_morning_reminders,
        CronTrigger(hour=10, minute=0, timezone=TIMEZONE),
        args=[bot],
        id="morning_reminders",
        name="Morning Task Reminders"
    )
    
    # Overdue alerts at 11:00 (to admins)
    scheduler.add_job(
        send_overdue_alerts,
        CronTrigger(hour=11, minute=0, timezone=TIMEZONE),
        args=[bot],
        id="overdue_alerts",
        name="Overdue Task Alerts"
    )
    
    # Hourly reminders (1 hour before task) 8:00-20:00
    scheduler.add_job(
        send_hourly_reminders,
        CronTrigger(hour="8-20", minute=0, timezone=TIMEZONE),
        args=[bot],
        id="hourly_reminders",
        name="Hourly Before-Task Reminders"
    )
    
    # Day-before reminders at 20:00 (tomorrow's tasks to assignees)
    scheduler.add_job(
        send_day_before_reminders,
        CronTrigger(hour=20, minute=0, timezone=TIMEZONE),
        args=[bot],
        id="day_before_reminders",
        name="Day-Before Reminders"
    )
    
    scheduler.start()
    logger.info(f"⏰ Scheduler started (timezone: {TIMEZONE})")
    logger.info("   09:00 — Morning report (admins)")
    logger.info("   10:00 — Morning reminders (assignees)")
    logger.info("   11:00 — Overdue alerts (admins)")
    logger.info("   8-20h — Hourly 1hr-before reminders")
    logger.info("   20:00 — Day-before reminders (assignees)")
    
    # Run startup
    await on_startup(bot)
    
    # Start polling
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
