import logging
import re
from datetime import date

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Booking, BookingSource, BookingStatus, Guest
from app.services.availability import get_available_beds

logger = logging.getLogger(__name__)

WA_API = "https://graph.facebook.com/v19.0"

# In-memory sessions keyed by phone number
sessions: dict[str, dict] = {}

CHOOSING, CHECKIN, CHECKOUT, SELECT_BED, GUEST_NAME, GUEST_EMAIL, CONFIRM = range(7)


async def _send(to: str, payload: dict) -> None:
    if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
        return
    url = f"{WA_API}/{settings.whatsapp_phone_number_id}/messages"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
            json={"messaging_product": "whatsapp", "to": to, **payload},
            timeout=10,
        )
        if r.status_code >= 400:
            logger.warning("WhatsApp send failed %s: %s", r.status_code, r.text)


async def send_text(to: str, text: str) -> None:
    await _send(to, {"type": "text", "text": {"body": text}})


async def send_buttons(to: str, text: str, buttons: list[tuple[str, str]]) -> None:
    await _send(to, {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": bid, "title": label}}
                for bid, label in buttons
            ]},
        },
    })


async def send_list(to: str, text: str, items: list[tuple[str, str, str]]) -> None:
    await _send(to, {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": "Select",
                "sections": [{"title": "Available Beds", "rows": [
                    {"id": row_id, "title": title[:24], "description": desc[:72]}
                    for row_id, title, desc in items
                ]}],
            },
        },
    })


async def notify_admin_whatsapp(text: str) -> None:
    if settings.whatsapp_admin_phone:
        await send_text(settings.whatsapp_admin_phone, text)


async def _start(phone: str) -> None:
    sessions[phone] = {"state": CHOOSING}
    await send_buttons(phone, "👋 Welcome to Bed Manager! What would you like to do?", [
        ("check", "📅 Check Availability"),
        ("book", "🛏 Book a Bed"),
    ])


async def _ask_checkin(phone: str) -> None:
    sessions[phone]["state"] = CHECKIN
    await send_text(phone, "📅 Enter check-in date (YYYY-MM-DD):")


async def handle_message(phone: str, text: str) -> None:
    text = text.strip()
    s = sessions.get(phone, {})
    state = s.get("state")

    if text.lower() in ("hi", "hello", "hola", "start", "/start") or state is None:
        await _start(phone)
        return

    if state == CHOOSING:
        if text in ("check", "book"):
            s["action"] = text
            await _ask_checkin(phone)
        else:
            await _start(phone)

    elif state == CHECKIN:
        try:
            s["check_in"] = date.fromisoformat(text)
            s["state"] = CHECKOUT
            await send_text(phone, "📅 Enter check-out date (YYYY-MM-DD):")
        except ValueError:
            await send_text(phone, "❌ Invalid date. Use YYYY-MM-DD (e.g. 2026-08-01):")

    elif state == CHECKOUT:
        try:
            check_out = date.fromisoformat(text)
        except ValueError:
            await send_text(phone, "❌ Invalid date. Use YYYY-MM-DD:")
            return
        if check_out <= s["check_in"]:
            await send_text(phone, "❌ Check-out must be after check-in:")
            return
        s["check_out"] = check_out

        async with AsyncSessionLocal() as db:
            beds = await get_available_beds(db, s["check_in"], check_out)

        if not beds:
            await send_text(phone, "😔 No beds available for those dates. Say 'hi' to start again.")
            sessions.pop(phone, None)
            return

        if s["action"] == "check":
            lines = [f"✅ Available ({s['check_in']} → {check_out}):\n"]
            for b in beds:
                price = f"${b['price_per_night']:.0f}/night" if b["price_per_night"] else "TBD"
                lines.append(f"• {b['bed_name']} — {b['room_name']} — {price}")
            await send_text(phone, "\n".join(lines))
            sessions.pop(phone, None)
            return

        s["beds"] = beds
        s["state"] = SELECT_BED
        items = [
            (
                f"bed_{i}",
                b["bed_name"],
                f"{b['room_name']} · {'$'+str(int(b['price_per_night']))+'/night' if b['price_per_night'] else 'No price'}",
            )
            for i, b in enumerate(beds)
        ]
        await send_list(phone, "🛏 Select a bed:", items)

    elif state == SELECT_BED:
        if not text.startswith("bed_"):
            await send_text(phone, "Please select a bed from the list above.")
            return
        idx = int(text.split("_")[1])
        s["bed"] = s["beds"][idx]
        s["state"] = GUEST_NAME
        await send_text(phone, "👤 Enter your full name (First Last):")

    elif state == GUEST_NAME:
        parts = text.split(None, 1)
        if len(parts) < 2:
            await send_text(phone, "Please enter first and last name (e.g. John Smith):")
            return
        s["first_name"], s["last_name"] = parts[0], parts[1]
        s["state"] = GUEST_EMAIL
        await send_text(phone, "📧 Enter your email address:")

    elif state == GUEST_EMAIL:
        email = text.lower()
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            await send_text(phone, "❌ Invalid email, try again:")
            return
        s["email"] = email
        bed = s["bed"]
        nights = (s["check_out"] - s["check_in"]).days
        total = f"${bed['price_per_night'] * nights:.0f}" if bed["price_per_night"] else "N/A"
        summary = (
            f"📋 Booking Summary\n\n"
            f"🛏 {bed['bed_name']} — {bed['room_name']}\n"
            f"📅 {s['check_in']} → {s['check_out']} ({nights} nights)\n"
            f"👤 {s['first_name']} {s['last_name']}\n"
            f"📧 {email}\n"
            f"💰 Total: {total}"
        )
        s["state"] = CONFIRM
        await send_buttons(phone, summary, [("confirm", "✅ Confirm"), ("cancel", "❌ Cancel")])

    elif state == CONFIRM:
        if text == "cancel":
            await send_text(phone, "❌ Booking cancelled. Say 'hi' to start again.")
            sessions.pop(phone, None)
            return
        if text != "confirm":
            await send_buttons(phone, "Please confirm or cancel:", [("confirm", "✅ Confirm"), ("cancel", "❌ Cancel")])
            return

        bed = s["bed"]
        nights = (s["check_out"] - s["check_in"]).days
        total = bed["price_per_night"] * nights if bed["price_per_night"] else None

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Guest).where(Guest.email == s["email"]))
            guest = result.scalar_one_or_none()
            if not guest:
                guest = Guest(first_name=s["first_name"], last_name=s["last_name"], email=s["email"])
                db.add(guest)
                await db.flush()

            booking = Booking(
                bed_id=bed["bed_id"],
                guest_id=guest.id,
                check_in=s["check_in"],
                check_out=s["check_out"],
                status=BookingStatus.confirmed,
                source=BookingSource.direct,
                total_price=total,
            )
            db.add(booking)
            await db.commit()
            await db.refresh(booking)

        await send_text(
            phone,
            f"✅ Booking confirmed!\n\n"
            f"ID: {booking.id[:8]}\n"
            f"Check-in: {s['check_in']}\n"
            f"Check-out: {s['check_out']}\n\n"
            f"See you soon! 🏨"
        )
        await notify_admin_whatsapp(
            f"🔔 New WhatsApp Booking\n"
            f"Bed: {bed['bed_name']} ({bed['room_name']})\n"
            f"Guest: {s['first_name']} {s['last_name']} ({s['email']})\n"
            f"Dates: {s['check_in']} → {s['check_out']}\n"
            f"ID: {booking.id[:8]}"
        )
        sessions.pop(phone, None)
