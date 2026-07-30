import asyncio
import json
import subprocess
from collections import defaultdict

import httpx
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import settings

_app: Application | None = None
_client: AsyncOpenAI | None = None
_histories: dict[int, list] = defaultdict(list)

ADMIN_SYSTEM = """You are AmaunaBot, the AI admin assistant for an AWS EC2 bed-booking server.
You can run shell commands and call the bed-manager REST API.
Key Docker services: bed-manager (port 13377), n8n, caddy, postgres.
Be concise. Use Telegram markdown (*bold*, `code`). Ask before destructive ops (restart, delete).
Always reply in the same language the user writes in."""

GUEST_SYSTEM = """You are AmaunaBot, the sales bot for Amauna — a group of boutique Colombian eco-hostels.
Properties: Jardín del Mar, Palmar del Viento, Refugio del Caimán.

YOUR GOAL: Close the sale. Get them from "interested" to "payment link sent" in one conversation.

━━ PERSONALITY MIRRORING ━━
In the first 1-2 messages, read the client's style:
- Formal/usted → match with warmth but respect
- Casual/tú/emojis → warm and professional Colombian tone. Use "listo" naturally and often. "chimba" and "bacano" almost never — only if the client themselves is very casual/young. Never force it.
- Family vibe → focus on comfort, safety, kid-friendly angle
- Young backpacker → adventure, freedom, good vibes
- Couple → romance, sunsets, intimacy
Adapt your pitch to what makes THEM excited, not a generic script.

━━ SALES FLOW ━━
1. Greet and immediately find out: dates, how many people, any kids, any pets — get this first, nothing else
2. Check availability for those dates
3. Present 1-2 best options — less is more, create desire
4. Handle objections naturally ("is it safe?", "what's included?", etc.)
5. Once they pick → collect name + email → create booking → send payment link
6. Payment link format: https://pay.amauna.co/booking/{booking_id} (mock)
7. Only ask "where did you hear about us?" casually AFTER the booking is confirmed — not before, never as a blocker

━━ SMART DEFAULTS ━━
- Name: accept "First Last" as-is. Never ask to split it. The API takes first_name + last_name — split it yourself internally (first word = first_name, rest = last_name).
- Dates: if someone says "mañana" / "tomorrow" / "hoy" infer check_in = today and check_out = tomorrow (1 night). Never ask for checkout if it's obvious.
- Groups: book ONE person first (the one who gave their details), then ask "¿quieres que reserve el resto del grupo también?" — don't demand all names upfront.
- Pets: Refugio del Caimán allows pets. Always check its availability via API before saying it's unavailable. Trust the API result.
- Language: detect in the very first message. English → respond 100% in English for the entire conversation. Spanish → Spanish. Mixed → follow the dominant language.

━━ FORMAT & TONE ━━
- No emojis except on purely informational lines (e.g. a bullet with a price or a link) where they genuinely aid readability — and even then, use one max per message
- Use bullet points and links for structure, not walls of text
- Professional, friendly, and direct — like a knowledgeable local friend, not a call-center agent
- Never start with praise ("¡Qué bueno!", "¡Excelente!", "¡Perfecto!") — just respond
- No filler words, no exclamation marks on every sentence
- "Listo" is your go-to closer. Slang otherwise: almost none.
- Short messages. Max 4 lines. This is Telegram, not email.
- Never list more than 2 options at once
- End with one clear next step or question, not a paragraph of options
- If they go quiet after pricing, one calm nudge: "Los fines de semana se llenan rápido, si quieres aseguro la cama."
- Kids allowed everywhere. Pets: only Refugio del Caimán.
- Prices are per bed per night in COP
- Always reply in the EXACT same language the user writes in. If they write in English, respond in English. If Spanish, respond in Spanish. No exceptions."""

ADMIN_TOOLS = [
    {"type": "function", "function": {
        "name": "shell_exec",
        "description": "Run a shell command on the server (docker, system info, etc.)",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}
        }, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "api_get",
        "description": "GET the bed-manager REST API. Paths: /bookings, /beds, /rooms, /properties, /availability?check_in=YYYY-MM-DD&check_out=YYYY-MM-DD",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "api_post",
        "description": "POST to bed-manager REST API. path e.g. /bookings, /guests. body: JSON string.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "body": {"type": "string"},
        }, "required": ["path", "body"]},
    }},
    {"type": "function", "function": {
        "name": "api_delete",
        "description": "DELETE via bed-manager REST API. path e.g. /bookings/{id}",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]},
    }},
]

GUEST_TOOLS = [
    {"type": "function", "function": {
        "name": "api_get",
        "description": "GET the bed-manager REST API. Paths: /availability?check_in=YYYY-MM-DD&check_out=YYYY-MM-DD, /beds, /rooms",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "book",
        "description": "Create a guest + booking in one call, then returns a payment link. Use this instead of api_post.",
        "parameters": {"type": "object", "properties": {
            "full_name": {"type": "string", "description": "Guest full name exactly as provided, e.g. 'Ana Lopez'"},
            "email": {"type": "string"},
            "bed_id": {"type": "string"},
            "check_in": {"type": "string", "description": "YYYY-MM-DD"},
            "check_out": {"type": "string", "description": "YYYY-MM-DD"},
            "total_cop": {"type": "integer"},
        }, "required": ["full_name", "email", "bed_id", "check_in", "check_out", "total_cop"]},
    }},
]


async def _run_tool(name: str, args: dict) -> str:
    if name == "shell_exec":
        r = subprocess.run(args["command"], shell=True, capture_output=True, text=True, timeout=30)
        out = (r.stdout + r.stderr).strip()
        return out[:3000] or "(no output)"
    if name == "api_get":
        async with httpx.AsyncClient() as c:
            r = await c.get(f"http://localhost:13377{args['path']}", timeout=10)
        return r.text[:3000]
    if name == "api_post":
        async with httpx.AsyncClient() as c:
            r = await c.post(f"http://localhost:13377{args['path']}",
                             content=args["body"], headers={"Content-Type": "application/json"}, timeout=10)
        return r.text[:3000]
    if name == "api_delete":
        async with httpx.AsyncClient() as c:
            r = await c.delete(f"http://localhost:13377{args['path']}", timeout=10)
        return r.text[:3000]
    if name == "generate_payment_link":
        name_enc = args["guest_name"].replace(" ", "+")
        return f"https://pay.amauna.co/booking/{args['booking_id']}?amount={args['amount_cop']}&guest={name_enc}"
    if name == "book":
        parts = args["full_name"].strip().split(None, 1)
        first, last = parts[0], parts[1] if len(parts) > 1 else parts[0]
        async with httpx.AsyncClient() as c:
            g = await c.post("http://localhost:13377/guests",
                             content=json.dumps({"first_name": first, "last_name": last, "email": args["email"]}),
                             headers={"Content-Type": "application/json"}, timeout=10)
            guest = g.json()
            if "id" not in guest:
                return f"guest error: {g.text}"
            b = await c.post("http://localhost:13377/bookings",
                             content=json.dumps({"bed_id": args["bed_id"], "guest_id": guest["id"],
                                                 "check_in": args["check_in"], "check_out": args["check_out"],
                                                 "total_price": args["total_cop"], "status": "confirmed", "source": "direct"}),
                             headers={"Content-Type": "application/json"}, timeout=10)
            booking = b.json()
            if "id" not in booking:
                return f"booking error: {b.text}"
        link = f"https://pay.amauna.co/booking/{booking['id']}?amount={args['total_cop']}&guest={args['full_name'].replace(' ','+')}"
        return f"booking_id={booking['id']} payment_link={link}"
    return f"unknown tool: {name}"


def _is_admin(chat_id: int) -> bool:
    return str(chat_id) == settings.telegram_admin_chat_id


async def _chat(chat_id: int, text: str) -> str:
    admin = _is_admin(chat_id)
    history = _histories[chat_id]
    history.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": ADMIN_SYSTEM if admin else GUEST_SYSTEM}] + history

    for _ in range(10):
        resp = await _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=ADMIN_TOOLS if admin else GUEST_TOOLS,
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            result = await _run_tool(tc.function.name, json.loads(tc.function.arguments))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    _histories[chat_id] = messages[1:][-40:]
    return msg.content or "..."


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.chat.send_action("typing")
    try:
        reply = await _chat(chat_id, update.message.text)
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def _cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _histories.pop(update.effective_chat.id, None)
    await update.message.reply_text("Conversation reset.")


async def notify_admin(text: str) -> None:
    if not _app or not settings.telegram_admin_chat_id:
        return
    try:
        await _app.bot.send_message(
            chat_id=settings.telegram_admin_chat_id, text=text, parse_mode="HTML"
        )
    except Exception:
        pass


async def start_bot() -> None:
    global _app, _client
    if not settings.telegram_bot_token or not settings.openai_api_key:
        return
    _client = AsyncOpenAI(api_key=settings.openai_api_key)
    _app = Application.builder().token(settings.telegram_bot_token).build()
    _app.add_handler(CommandHandler("reset", _cmd_reset))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(drop_pending_updates=True)


async def stop_bot() -> None:
    global _app
    if _app:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
        _app = None
