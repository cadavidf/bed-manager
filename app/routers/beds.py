from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Bed, Room
from app.schemas import BedCreate, BedOut, BedUpdate

router = APIRouter(prefix="/beds", tags=["beds"])


@router.get("", response_model=list[BedOut])
async def list_beds(
    room_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Bed)
    if room_id:
        stmt = stmt.where(Bed.room_id == room_id)
    result = await db.execute(stmt.order_by(Bed.name))
    return result.scalars().all()


@router.post("", response_model=BedOut, status_code=status.HTTP_201_CREATED)
async def create_bed(body: BedCreate, db: AsyncSession = Depends(get_db)):
    if not await db.get(Room, body.room_id):
        raise HTTPException(status_code=404, detail="Room not found")
    bed = Bed(**body.model_dump())
    db.add(bed)
    await db.commit()
    await db.refresh(bed)
    return bed


@router.get("/{bed_id}", response_model=BedOut)
async def get_bed(bed_id: str, db: AsyncSession = Depends(get_db)):
    bed = await db.get(Bed, bed_id)
    if not bed:
        raise HTTPException(status_code=404, detail="Bed not found")
    return bed


@router.patch("/{bed_id}", response_model=BedOut)
async def update_bed(bed_id: str, body: BedUpdate, db: AsyncSession = Depends(get_db)):
    bed = await db.get(Bed, bed_id)
    if not bed:
        raise HTTPException(status_code=404, detail="Bed not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(bed, field, value)
    await db.commit()
    await db.refresh(bed)
    return bed


@router.delete("/{bed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bed(bed_id: str, db: AsyncSession = Depends(get_db)):
    bed = await db.get(Bed, bed_id)
    if not bed:
        raise HTTPException(status_code=404, detail="Bed not found")
    await db.delete(bed)
    await db.commit()
