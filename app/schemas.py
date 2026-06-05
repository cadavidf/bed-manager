from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator

from app.models import BedType, BookingSource, BookingStatus, RoomType, SeasonTier


# ── Property ─────────────────────────────────────────────────────────────────

class PropertyCreate(BaseModel):
    name: str
    address: Optional[str] = None
    description: Optional[str] = None


class PropertyUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None


class PropertyOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    name: str
    address: Optional[str]
    description: Optional[str]
    created_at: datetime


# ── Room ──────────────────────────────────────────────────────────────────────

class RoomCreate(BaseModel):
    property_id: str
    name: str
    type: RoomType
    capacity: int = 1
    price_per_night: Optional[float] = None
    description: Optional[str] = None


class RoomUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[RoomType] = None
    capacity: Optional[int] = None
    price_per_night: Optional[float] = None
    description: Optional[str] = None


class RoomOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    property_id: str
    name: str
    type: RoomType
    capacity: int
    price_per_night: Optional[float]
    description: Optional[str]


# ── Bed ───────────────────────────────────────────────────────────────────────

class BedCreate(BaseModel):
    room_id: str
    name: str
    type: BedType = BedType.single
    price_per_night: Optional[float] = None
    is_active: bool = True


class BedUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[BedType] = None
    price_per_night: Optional[float] = None
    is_active: Optional[bool] = None


class BedOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    room_id: str
    name: str
    type: BedType
    price_per_night: Optional[float]
    is_active: bool


# ── Guest ─────────────────────────────────────────────────────────────────────

class GuestCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None
    id_number: Optional[str] = None
    notes: Optional[str] = None


class GuestUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    id_number: Optional[str] = None
    notes: Optional[str] = None


class GuestOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    first_name: str
    last_name: str
    email: str
    phone: Optional[str]
    id_number: Optional[str]
    notes: Optional[str]
    created_at: datetime


# ── Booking ───────────────────────────────────────────────────────────────────

class BookingCreate(BaseModel):
    bed_id: str
    guest_id: Optional[str] = None
    check_in: date
    check_out: date
    status: BookingStatus = BookingStatus.pending
    source: BookingSource = BookingSource.direct
    total_price: Optional[float] = None
    notes: Optional[str] = None
    external_id: Optional[str] = None

    @field_validator("check_out")
    @classmethod
    def check_out_after_check_in(cls, v, info):
        if info.data.get("check_in") and v <= info.data["check_in"]:
            raise ValueError("check_out must be after check_in")
        return v


class BookingUpdate(BaseModel):
    status: Optional[BookingStatus] = None
    total_price: Optional[float] = None
    notes: Optional[str] = None
    guest_id: Optional[str] = None


class BookingOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    bed_id: str
    guest_id: Optional[str]
    check_in: date
    check_out: date
    status: BookingStatus
    source: BookingSource
    total_price: Optional[float]
    notes: Optional[str]
    external_id: Optional[str]
    created_at: datetime
    updated_at: datetime


# ── Availability ──────────────────────────────────────────────────────────────

class AvailableBed(BaseModel):
    bed_id: str
    bed_name: str
    bed_type: BedType
    room_id: str
    room_name: str
    room_type: RoomType
    property_id: str
    property_name: str
    price_per_night: Optional[float]
    season_tier: Optional[str]
    nights: int
    total_price: Optional[float]


# ── Seasonal Rates ────────────────────────────────────────────────────────────

class SeasonalRateCreate(BaseModel):
    property_id: str
    name: str
    tier: SeasonTier
    start_date: date
    end_date: date
    price_per_night: float

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v, info):
        if info.data.get("start_date") and v < info.data["start_date"]:
            raise ValueError("end_date must be >= start_date")
        return v


class SeasonalRateUpdate(BaseModel):
    name: Optional[str] = None
    tier: Optional[SeasonTier] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    price_per_night: Optional[float] = None


class SeasonalRateOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    property_id: str
    name: str
    tier: SeasonTier
    start_date: date
    end_date: date
    price_per_night: float


class AvailabilityRequest(BaseModel):
    property_id: Optional[str] = None
    check_in: date
    check_out: date

    @field_validator("check_out")
    @classmethod
    def check_out_after_check_in(cls, v, info):
        if info.data.get("check_in") and v <= info.data["check_in"]:
            raise ValueError("check_out must be after check_in")
        return v


# ── External Calendar ─────────────────────────────────────────────────────────

class ExternalCalendarCreate(BaseModel):
    bed_id: str
    name: str
    ical_url: str
    platform: str = "other"


class ExternalCalendarOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    bed_id: str
    name: str
    ical_url: str
    platform: str
    last_synced: Optional[datetime]
    is_active: bool


# ── Webhook ───────────────────────────────────────────────────────────────────

class WebhookBookingPayload(BaseModel):
    """Payload sent by external website to create a booking via webhook."""
    bed_id: str
    check_in: date
    check_out: date
    guest_first_name: str
    guest_last_name: str
    guest_email: EmailStr
    guest_phone: Optional[str] = None
    notes: Optional[str] = None
    external_id: Optional[str] = None
    secret: str
