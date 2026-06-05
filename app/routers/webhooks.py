"""
Webhook endpoint for external website booking widget.
The booking widget (widget/index.html) POSTs to this endpoint when a customer
completes a booking on your website.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Bed, Booking, BookingSource, BookingStatus, Guest
from app.routers.bookings import _check_conflict
from app.schemas import BookingOut, WebhookBookingPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post(
    "/booking",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Receive a booking from an external website widget",
)
async def receive_webhook_booking(body: WebhookBookingPayload, db: AsyncSession = Depends(get_db)):
    if body.secret != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    bed = await db.get(Bed, body.bed_id)
    if not bed:
        raise HTTPException(status_code=404, detail="Bed not found")

    if await _check_conflict(db, body.bed_id, body.check_in, body.check_out):
        raise HTTPException(status_code=409, detail="Bed is not available for the requested dates")

    # Find or create guest by email
    from sqlalchemy import select
    result = await db.execute(
        select(Guest).where(Guest.email == body.guest_email.lower())
    )
    guest = result.scalar_one_or_none()
    if not guest:
        guest = Guest(
            first_name=body.guest_first_name,
            last_name=body.guest_last_name,
            email=body.guest_email.lower(),
            phone=body.guest_phone,
        )
        db.add(guest)
        await db.flush()

    booking = Booking(
        bed_id=body.bed_id,
        guest_id=guest.id,
        check_in=body.check_in,
        check_out=body.check_out,
        status=BookingStatus.confirmed,
        source=BookingSource.webhook,
        notes=body.notes,
        external_id=body.external_id,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    logger.info("Webhook booking created: %s for guest %s", booking.id, guest.email)
    return booking
