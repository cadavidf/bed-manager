from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import engine
from app.models import Base
from app.routers import availability, beds, bookings, guests, ical, properties, rooms, seasonal_rates, webhooks, whatsapp
from app.scheduler import start_scheduler, stop_scheduler
from app.services.telegram_bot import start_bot, stop_bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    start_scheduler()
    await start_bot()
    yield
    await stop_bot()
    stop_scheduler()


app = FastAPI(
    title="Bed Manager",
    description=(
        "Property, room, and bed management API with Airbnb/Booking.com iCal sync "
        "and webhook support for external booking widgets."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(properties.router)
app.include_router(rooms.router)
app.include_router(beds.router)
app.include_router(guests.router)
app.include_router(bookings.router)
app.include_router(availability.router)
app.include_router(ical.router)
app.include_router(seasonal_rates.router)
app.include_router(webhooks.router)
app.include_router(whatsapp.router)

# Serve the booking widget and demo site
app.mount("/widget", StaticFiles(directory="widget", html=True), name="widget")
app.mount("/demo", StaticFiles(directory="demo", html=True), name="demo")


@app.get("/", tags=["health"])
async def health():
    return {"status": "ok", "service": "bed-manager"}
