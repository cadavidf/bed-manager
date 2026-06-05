from datetime import datetime, timezone

from icalendar import Calendar, Event, vText
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Bed, Booking, BookingStatus


async def generate_ical_feed(db: AsyncSession, bed_id: str) -> bytes:
    """
    Generate an iCal feed for a bed.
    Paste the URL of this endpoint into Airbnb or Booking.com as an external calendar
    to block off dates when the bed is already booked.
    """
    stmt = (
        select(Booking)
        .options(joinedload(Booking.guest), joinedload(Booking.bed).joinedload(Bed.room))
        .where(
            Booking.bed_id == bed_id,
            Booking.status.in_([
                BookingStatus.confirmed,
                BookingStatus.pending,
                BookingStatus.checked_in,
            ]),
        )
    )
    result = await db.execute(stmt)
    bookings = result.unique().scalars().all()

    cal = Calendar()
    cal.add("prodid", "-//BedManager//BedManager//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")

    for booking in bookings:
        event = Event()
        event.add("uid", booking.id)
        event.add("dtstart", booking.check_in)
        event.add("dtend", booking.check_out)
        event.add("dtstamp", datetime.now(timezone.utc))
        event.add("summary", vText("Blocked"))
        event.add("status", "CONFIRMED")
        cal.add_component(event)

    return cal.to_ical()
