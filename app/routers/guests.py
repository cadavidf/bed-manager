from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Guest
from app.schemas import GuestCreate, GuestOut, GuestUpdate

router = APIRouter(prefix="/guests", tags=["guests"])


@router.get("", response_model=list[GuestOut])
async def list_guests(
    email: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Guest)
    if email:
        stmt = stmt.where(Guest.email == email.lower())
    result = await db.execute(stmt.order_by(Guest.last_name, Guest.first_name))
    return result.scalars().all()


@router.post("", response_model=GuestOut, status_code=status.HTTP_201_CREATED)
async def create_guest(body: GuestCreate, db: AsyncSession = Depends(get_db)):
    data = body.model_dump()
    data["email"] = data["email"].lower()
    guest = Guest(**data)
    db.add(guest)
    await db.commit()
    await db.refresh(guest)
    return guest


@router.get("/{guest_id}", response_model=GuestOut)
async def get_guest(guest_id: str, db: AsyncSession = Depends(get_db)):
    guest = await db.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    return guest


@router.patch("/{guest_id}", response_model=GuestOut)
async def update_guest(guest_id: str, body: GuestUpdate, db: AsyncSession = Depends(get_db)):
    guest = await db.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    data = body.model_dump(exclude_none=True)
    if "email" in data:
        data["email"] = data["email"].lower()
    for field, value in data.items():
        setattr(guest, field, value)
    await db.commit()
    await db.refresh(guest)
    return guest


@router.delete("/{guest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_guest(guest_id: str, db: AsyncSession = Depends(get_db)):
    guest = await db.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    await db.delete(guest)
    await db.commit()
