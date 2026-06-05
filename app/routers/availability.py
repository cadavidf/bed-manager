from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import AvailableBed
from app.services.availability import get_available_beds

router = APIRouter(prefix="/availability", tags=["availability"])


@router.get("", response_model=list[AvailableBed])
async def check_availability(
    check_in: date = Query(..., description="Check-in date (YYYY-MM-DD)"),
    check_out: date = Query(..., description="Check-out date (YYYY-MM-DD)"),
    property_id: Optional[str] = Query(None, description="Filter by property"),
    db: AsyncSession = Depends(get_db),
):
    return await get_available_beds(db, check_in, check_out, property_id)
