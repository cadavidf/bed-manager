from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Property, SeasonalRate
from app.schemas import SeasonalRateCreate, SeasonalRateOut, SeasonalRateUpdate

router = APIRouter(prefix="/seasonal-rates", tags=["seasonal-rates"])


@router.get("", response_model=list[SeasonalRateOut])
async def list_rates(
    property_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SeasonalRate).order_by(SeasonalRate.start_date)
    if property_id:
        stmt = stmt.where(SeasonalRate.property_id == property_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=SeasonalRateOut, status_code=status.HTTP_201_CREATED)
async def create_rate(body: SeasonalRateCreate, db: AsyncSession = Depends(get_db)):
    if not await db.get(Property, body.property_id):
        raise HTTPException(status_code=404, detail="Property not found")
    rate = SeasonalRate(**body.model_dump())
    db.add(rate)
    await db.commit()
    await db.refresh(rate)
    return rate


@router.patch("/{rate_id}", response_model=SeasonalRateOut)
async def update_rate(rate_id: str, body: SeasonalRateUpdate, db: AsyncSession = Depends(get_db)):
    rate = await db.get(SeasonalRate, rate_id)
    if not rate:
        raise HTTPException(status_code=404, detail="Seasonal rate not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(rate, field, value)
    await db.commit()
    await db.refresh(rate)
    return rate


@router.delete("/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rate(rate_id: str, db: AsyncSession = Depends(get_db)):
    rate = await db.get(SeasonalRate, rate_id)
    if not rate:
        raise HTTPException(status_code=404, detail="Seasonal rate not found")
    await db.delete(rate)
    await db.commit()
