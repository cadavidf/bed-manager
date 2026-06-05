from __future__ import annotations
from datetime import date
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Bed, Booking, BookingStatus, Property, Room, SeasonalRate, SeasonTier

TIER_PRIORITY = {
    SeasonTier.super_alta: 4,
    SeasonTier.alta: 3,
    SeasonTier.media: 2,
    SeasonTier.baja: 1,
}


async def _get_seasonal_price(
    db: AsyncSession,
    property_id: str,
    check_in: date,
    check_out: date,
    base_price: Optional[float],
) -> tuple:
    stmt = select(SeasonalRate).where(
        and_(
            SeasonalRate.property_id == property_id,
            SeasonalRate.start_date <= check_out,
            SeasonalRate.end_date >= check_in,
        )
    )
    result = await db.execute(stmt)
    rates = result.scalars().all()
    if not rates:
        return base_price, None
    best = max(rates, key=lambda r: TIER_PRIORITY.get(r.tier, 0))
    return best.price_per_night, best.tier.value


async def get_available_beds(
    db: AsyncSession,
    check_in: date,
    check_out: date,
    property_id: Optional[str] = None,
) -> list:
    conflict_subq = (
        select(Booking.bed_id)
        .where(
            and_(
                Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending, BookingStatus.checked_in]),
                Booking.check_in < check_out,
                Booking.check_out > check_in,
            )
        )
        .scalar_subquery()
    )

    stmt = (
        select(Bed)
        .options(joinedload(Bed.room).joinedload(Room.property))
        .join(Room)
        .join(Property)
        .where(
            and_(
                Bed.is_active == True,
                Bed.id.not_in(conflict_subq),
                Property.id == property_id if property_id else True,
            )
        )
    )

    result = await db.execute(stmt)
    beds = result.unique().scalars().all()

    nights = (check_out - check_in).days
    available = []
    for bed in beds:
        base_price = bed.price_per_night or bed.room.price_per_night
        price, tier = await _get_seasonal_price(
            db, bed.room.property.id, check_in, check_out, base_price
        )
        available.append({
            "bed_id": bed.id,
            "bed_name": bed.name,
            "bed_type": bed.type,
            "room_id": bed.room.id,
            "room_name": bed.room.name,
            "room_type": bed.room.type,
            "property_id": bed.room.property.id,
            "property_name": bed.room.property.name,
            "price_per_night": price,
            "season_tier": tier,
            "nights": nights,
            "total_price": price * nights if price else None,
        })

    return available
