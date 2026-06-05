from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Bed, ExternalCalendar
from app.schemas import ExternalCalendarCreate, ExternalCalendarOut
from app.services.ical_export import generate_ical_feed
from app.services.ical_import import sync_external_calendar

router = APIRouter(tags=["ical"])


# ── iCal export (paste this URL into Airbnb/Booking.com) ─────────────────────

@router.get(
    "/ical/{bed_id}",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
    summary="Export iCal feed for a bed (paste into Airbnb/Booking.com)",
)
async def export_ical(bed_id: str, db: AsyncSession = Depends(get_db)):
    bed = await db.get(Bed, bed_id)
    if not bed:
        raise HTTPException(status_code=404, detail="Bed not found")
    data = await generate_ical_feed(db, bed_id)
    return Response(content=data, media_type="text/calendar")


# ── External calendars (import from Airbnb/Booking.com) ──────────────────────

@router.get("/external-calendars", response_model=list[ExternalCalendarOut], tags=["ical"])
async def list_external_calendars(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ExternalCalendar))
    return result.scalars().all()


@router.post(
    "/external-calendars",
    response_model=ExternalCalendarOut,
    status_code=status.HTTP_201_CREATED,
    tags=["ical"],
    summary="Register an Airbnb/Booking.com iCal feed to import blocked dates",
)
async def add_external_calendar(body: ExternalCalendarCreate, db: AsyncSession = Depends(get_db)):
    if not await db.get(Bed, body.bed_id):
        raise HTTPException(status_code=404, detail="Bed not found")
    cal = ExternalCalendar(**body.model_dump())
    db.add(cal)
    await db.commit()
    await db.refresh(cal)
    # Trigger an immediate sync
    synced = await sync_external_calendar(db, cal)
    await db.refresh(cal)
    return cal


@router.post(
    "/external-calendars/{calendar_id}/sync",
    response_model=ExternalCalendarOut,
    tags=["ical"],
    summary="Force-sync a single external calendar now",
)
async def force_sync(calendar_id: str, db: AsyncSession = Depends(get_db)):
    cal = await db.get(ExternalCalendar, calendar_id)
    if not cal:
        raise HTTPException(status_code=404, detail="External calendar not found")
    await sync_external_calendar(db, cal)
    await db.refresh(cal)
    return cal


@router.delete("/external-calendars/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["ical"])
async def delete_external_calendar(calendar_id: str, db: AsyncSession = Depends(get_db)):
    cal = await db.get(ExternalCalendar, calendar_id)
    if not cal:
        raise HTTPException(status_code=404, detail="External calendar not found")
    await db.delete(cal)
    await db.commit()
