"""
Poll external iCal feeds (Airbnb, Booking.com) and create/update blocking bookings.
Both platforms provide a "sync calendar" iCal URL you can copy from their dashboards.
"""
import logging
from datetime import datetime, timezone

import httpx
from icalendar import Calendar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Booking, BookingSource, BookingStatus, ExternalCalendar

logger = logging.getLogger(__name__)


async def sync_external_calendar(db: AsyncSession, calendar: ExternalCalendar) -> int:
    """Fetch one iCal feed and upsert blocked bookings. Returns count of upserted events."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(calendar.ical_url)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to fetch iCal for calendar %s: %s", calendar.id, exc)
            return 0

    try:
        cal = Calendar.from_ical(response.content)
    except Exception as exc:
        logger.warning("Failed to parse iCal for calendar %s: %s", calendar.id, exc)
        return 0

    count = 0
    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        uid = str(component.get("uid", ""))
        dtstart = component.get("dtstart")
        dtend = component.get("dtend")
        if not (uid and dtstart and dtend):
            continue

        check_in = dtstart.dt
        check_out = dtend.dt
        if hasattr(check_in, "date"):
            check_in = check_in.date()
        if hasattr(check_out, "date"):
            check_out = check_out.date()

        # Upsert: if external booking already exists, skip
        existing = await db.execute(
            select(Booking).where(
                Booking.external_id == uid,
                Booking.source == BookingSource.ical,
                Booking.bed_id == calendar.bed_id,
            )
        )
        if existing.scalar_one_or_none():
            continue

        booking = Booking(
            bed_id=calendar.bed_id,
            check_in=check_in,
            check_out=check_out,
            status=BookingStatus.confirmed,
            source=BookingSource.ical,
            external_id=uid,
            notes=f"Imported from {calendar.name} ({calendar.platform})",
        )
        db.add(booking)
        count += 1

    if count:
        await db.commit()

    calendar.last_synced = datetime.now(timezone.utc)
    await db.commit()

    return count


async def sync_all_calendars() -> None:
    """Called by the scheduler to poll all active external calendars."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExternalCalendar).where(ExternalCalendar.is_active == True)
        )
        calendars = result.scalars().all()
        for cal in calendars:
            synced = await sync_external_calendar(db, cal)
            if synced:
                logger.info("Synced %d events from %s (%s)", synced, cal.name, cal.platform)
