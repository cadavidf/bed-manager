import logging
import re
from datetime import date

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Booking, BookingSource, BookingStatus, Guest
from app.services.availability import get_available_beds

logger = logging.getLogger(__name__)

CHOOSING, CHECKIN, CHECKOUT, SELECT_BED, GUEST_NAME, GUEST_EMAIL, CONFIRM = range(7)

_app: Application | None = None


async def notify_admin(text: str) -> None:
    if _app is None or not settings.telegram_admin_chat_id:
        return
    try:
        await _app.bot.send_message(
            chat_id=settings.telegram_admin_chat_id,
            text=text,
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("Telegram admin notify failed: %s", exc)


def _is_admin(update: Update) -> bool:
    return bool(
        settings.telegram_admin_chat_id
        and str(update.effective_chat.id) == settings.telegram_admin_chat_id
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    keyboard = [[
        InlineKeyboardButton("📅 Check Availability", callback_data="check"),
        InlineKeyboardButton("🛏 Book a Bed", callback_data="book"),
    ]]
    if _is_admin(update):
        keyboard.append([InlineKeyboardButton("📋 Upcoming Bookings", callback_data="admin_list")])
    await update.message.reply_text(
        "👋 Welcome to *Bed Manager*! What would you like to do?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSING


async def btn_choosing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "admin_list":
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Booking)
                .where(Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending]))
                .order_by(Booking.check_in)
                .limit(10)
            )
            bookings = result.scalars().all()
        if not bookings:
            await query.edit_message_text("No upcoming bookings.")
        else:
            lines = ["📋 *Upcoming Bookings:*\n"]
            for b in bookings:
                lines.append(f"• `{b.id[:8]}` {b.check_in} → {b.check_out} [{b.status.value}]")
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data["action"] = query.data
    await query.edit_message_text("📅 Enter *check-in date* (YYYY-MM-DD):", parse_mode="Markdown")
    return CHECKIN


async def get_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["check_in"] = date.fromisoformat(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid date. Use YYYY-MM-DD (e.g. 2026-08-01):")
        return CHECKIN
    await update.message.reply_text("📅 Enter *check-out date* (YYYY-MM-DD):", parse_mode="Markdown")
    return CHECKOUT


async def get_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        check_out = date.fromisoformat(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid date. Use YYYY-MM-DD:")
        return CHECKOUT

    check_in: date = context.user_data["check_in"]
    if check_out <= check_in:
        await update.message.reply_text("❌ Check-out must be after check-in:")
        return CHECKOUT
    context.user_data["check_out"] = check_out

    async with AsyncSessionLocal() as db:
        beds = await get_available_beds(db, check_in, check_out)

    if not beds:
        await update.message.reply_text("😔 No beds available for those dates. /start to try again.")
        return ConversationHandler.END

    if context.user_data["action"] == "check":
        lines = [f"✅ *Available ({check_in} → {check_out}):*\n"]
        for b in beds:
            price = f"${b['price_per_night']:.0f}/night" if b["price_per_night"] else "price TBD"
            lines.append(f"• {b['bed_name']} — {b['room_name']} — {price}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data["beds"] = beds
    keyboard = [
        [InlineKeyboardButton(
            f"{b['bed_name']} ({b['room_name']})"
            + (f" · ${b['price_per_night']:.0f}/night" if b["price_per_night"] else ""),
            callback_data=f"bed_{i}",
        )]
        for i, b in enumerate(beds)
    ]
    await update.message.reply_text("🛏 Select a bed:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_BED


async def select_bed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    context.user_data["bed"] = context.user_data["beds"][idx]
    await query.edit_message_text("👤 Enter your *full name* (First Last):", parse_mode="Markdown")
    return GUEST_NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.strip().split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text("Please enter first and last name (e.g. John Smith):")
        return GUEST_NAME
    context.user_data["first_name"], context.user_data["last_name"] = parts[0], parts[1]
    await update.message.reply_text("📧 Enter your *email address*:", parse_mode="Markdown")
    return GUEST_EMAIL


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip().lower()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await update.message.reply_text("❌ Invalid email, try again:")
        return GUEST_EMAIL
    context.user_data["email"] = email

    d = context.user_data
    bed = d["bed"]
    nights = (d["check_out"] - d["check_in"]).days
    total = f"${bed['price_per_night'] * nights:.0f}" if bed["price_per_night"] else "N/A"

    await update.message.reply_text(
        f"📋 *Booking Summary*\n\n"
        f"🛏 {bed['bed_name']} — {bed['room_name']}\n"
        f"📅 {d['check_in']} → {d['check_out']} ({nights} nights)\n"
        f"👤 {d['first_name']} {d['last_name']}\n"
        f"📧 {email}\n"
        f"💰 Total: {total}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
        ]]),
    )
    return CONFIRM


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Booking cancelled. /start to begin again.")
        return ConversationHandler.END

    d = context.user_data
    bed = d["bed"]
    nights = (d["check_out"] - d["check_in"]).days
    total = bed["price_per_night"] * nights if bed["price_per_night"] else None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Guest).where(Guest.email == d["email"]))
        guest = result.scalar_one_or_none()
        if not guest:
            guest = Guest(first_name=d["first_name"], last_name=d["last_name"], email=d["email"])
            db.add(guest)
            await db.flush()

        booking = Booking(
            bed_id=bed["bed_id"],
            guest_id=guest.id,
            check_in=d["check_in"],
            check_out=d["check_out"],
            status=BookingStatus.confirmed,
            source=BookingSource.direct,
            total_price=total,
        )
        db.add(booking)
        await db.commit()
        await db.refresh(booking)

    await query.edit_message_text(
        f"✅ *Booking confirmed!*\n\n"
        f"ID: `{booking.id[:8]}`\n"
        f"Check-in: {d['check_in']}\n"
        f"Check-out: {d['check_out']}\n\n"
        f"See you soon! 🏨",
        parse_mode="Markdown",
    )
    await notify_admin(
        f"🔔 <b>New Telegram Booking</b>\n"
        f"Bed: {bed['bed_name']} ({bed['room_name']})\n"
        f"Guest: {d['first_name']} {d['last_name']} ({d['email']})\n"
        f"Dates: {d['check_in']} → {d['check_out']}\n"
        f"ID: <code>{booking.id[:8]}</code>"
    )
    return ConversationHandler.END


async def cmd_cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /cancel_booking <id_prefix>")
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Booking).where(Booking.id.startswith(context.args[0])))
        booking = result.scalar_one_or_none()
        if not booking:
            await update.message.reply_text(f"Booking `{context.args[0]}` not found.", parse_mode="Markdown")
            return
        booking.status = BookingStatus.cancelled
        await db.commit()
    await update.message.reply_text(f"✅ Booking `{context.args[0]}` cancelled.", parse_mode="Markdown")


async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Cancelled. /start to begin again.")
    return ConversationHandler.END


def _build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            CHOOSING:   [CallbackQueryHandler(btn_choosing, pattern="^(check|book|admin_list)$")],
            CHECKIN:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_checkin)],
            CHECKOUT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_checkout)],
            SELECT_BED: [CallbackQueryHandler(select_bed, pattern=r"^bed_\d+$")],
            GUEST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GUEST_EMAIL:[MessageHandler(filters.TEXT & ~filters.COMMAND, get_email)],
            CONFIRM:    [CallbackQueryHandler(confirm_booking, pattern="^(confirm|cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", conv_cancel)],
        per_user=True,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("cancel_booking", cmd_cancel_booking))
    return app


async def start_bot() -> None:
    global _app
    if not settings.telegram_bot_token:
        logger.info("TELEGRAM_BOT_TOKEN not set — bot disabled.")
        return
    _app = _build_app(settings.telegram_bot_token)
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot polling started.")


async def stop_bot() -> None:
    global _app
    if _app is None:
        return
    await _app.updater.stop()
    await _app.stop()
    await _app.shutdown()
    _app = None
