import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.services.ical_import import sync_all_calendars

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler():
    scheduler.add_job(
        sync_all_calendars,
        "interval",
        minutes=settings.ical_poll_interval_minutes,
        id="ical_sync",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("iCal scheduler started (every %d min)", settings.ical_poll_interval_minutes)


def stop_scheduler():
    scheduler.shutdown(wait=False)
