from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Bed, Booking, BookingStatus, Guest
from app.schemas import BookingCreate, BookingOut, BookingUpdate

router = APIRouter(prefix="/bookings", tags=["bookings"])


async def _check_conflict(
    db: AsyncSession,
    bed_id: str,
    check_in,
    check_out,
    exclude_booking_id: Optional[str] = None,
) -> bool:
    stmt = select(Booking).where(
        and_(
            Booking.bed_id == bed_id,
            Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending, BookingStatus.checked_in]),
            Booking.check_in < check_out,
            Booking.check_out > check_in,
        )
    )
    if exclude_booking_id:
        stmt = stmt.where(Booking.id != exclude_booking_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


@router.get("", response_model=list[BookingOut])
async def list_bookings(
    bed_id: Optional[str] = Query(None),
    status: Optional[BookingStatus] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Booking).order_by(Booking.check_in)
    if bed_id:
        stmt = stmt.where(Booking.bed_id == bed_id)
    if status:
        stmt = stmt.where(Booking.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking(body: BookingCreate, db: AsyncSession = Depends(get_db)):
    if not await db.get(Bed, body.bed_id):
        raise HTTPException(status_code=404, detail="Bed not found")
    if body.guest_id and not await db.get(Guest, body.guest_id):
        raise HTTPException(status_code=404, detail="Guest not found")
    if await _check_conflict(db, body.bed_id, body.check_in, body.check_out):
        raise HTTPException(status_code=409, detail="Bed is not available for the requested dates")
    booking = Booking(**body.model_dump())
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking


@router.get("/{booking_id}", response_model=BookingOut)
async def get_booking(booking_id: str, db: AsyncSession = Depends(get_db)):
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.patch("/{booking_id}", response_model=BookingOut)
async def update_booking(booking_id: str, body: BookingUpdate, db: AsyncSession = Depends(get_db)):
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if body.guest_id and not await db.get(Guest, body.guest_id):
        raise HTTPException(status_code=404, detail="Guest not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(booking, field, value)
    await db.commit()
    await db.refresh(booking)
    return booking


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_booking(booking_id: str, db: AsyncSession = Depends(get_db)):
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    booking.status = BookingStatus.cancelled
    await db.commit()
