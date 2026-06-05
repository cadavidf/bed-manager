from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


class RoomType(str, enum.Enum):
    private = "private"
    dorm = "dorm"


class BedType(str, enum.Enum):
    single = "single"
    double = "double"
    bunk_top = "bunk_top"
    bunk_bottom = "bunk_bottom"
    sofa = "sofa"


class BookingStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    checked_in = "checked_in"
    checked_out = "checked_out"


class SeasonTier(str, enum.Enum):
    baja = "baja"
    media = "media"
    alta = "alta"
    super_alta = "super_alta"


class BookingSource(str, enum.Enum):
    direct = "direct"
    airbnb = "airbnb"
    booking = "booking"
    webhook = "webhook"
    ical = "ical"


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    rooms: Mapped[List["Room"]] = relationship(back_populates="property", cascade="all, delete-orphan")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[RoomType] = mapped_column(Enum(RoomType), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    price_per_night: Mapped[Optional[float]] = mapped_column(Float)
    description: Mapped[Optional[str]] = mapped_column(Text)

    property: Mapped["Property"] = relationship(back_populates="rooms")
    beds: Mapped[List["Bed"]] = relationship(back_populates="room", cascade="all, delete-orphan")


class Bed(Base):
    __tablename__ = "beds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[BedType] = mapped_column(Enum(BedType), nullable=False, default=BedType.single)
    price_per_night: Mapped[Optional[float]] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    room: Mapped["Room"] = relationship(back_populates="beds")
    bookings: Mapped[List["Booking"]] = relationship(back_populates="bed", cascade="all, delete-orphan")
    external_calendars: Mapped[List["ExternalCalendar"]] = relationship(back_populates="bed", cascade="all, delete-orphan")


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    id_number: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    bookings: Mapped[List["Booking"]] = relationship(back_populates="guest")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_booking_external_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    bed_id: Mapped[str] = mapped_column(ForeignKey("beds.id", ondelete="CASCADE"), nullable=False)
    guest_id: Mapped[Optional[str]] = mapped_column(ForeignKey("guests.id", ondelete="SET NULL"))
    check_in: Mapped[datetime] = mapped_column(Date, nullable=False)
    check_out: Mapped[datetime] = mapped_column(Date, nullable=False)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.pending)
    source: Mapped[BookingSource] = mapped_column(Enum(BookingSource), default=BookingSource.direct)
    total_price: Mapped[Optional[float]] = mapped_column(Float)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    external_id: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    bed: Mapped["Bed"] = relationship(back_populates="bookings")
    guest: Mapped[Optional["Guest"]] = relationship(back_populates="bookings")


class ExternalCalendar(Base):
    """iCal feed from Airbnb, Booking.com, or any OTA."""
    __tablename__ = "external_calendars"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    bed_id: Mapped[str] = mapped_column(ForeignKey("beds.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ical_url: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String(50), default="other")
    last_synced: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    bed: Mapped["Bed"] = relationship(back_populates="external_calendars")


class SeasonalRate(Base):
    """Date-range based pricing tiers (Baja / Media / Alta / Super Alta)."""
    __tablename__ = "seasonal_rates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[SeasonTier] = mapped_column(Enum(SeasonTier), nullable=False)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    price_per_night: Mapped[float] = mapped_column(Float, nullable=False)

    property: Mapped["Property"] = relationship()
