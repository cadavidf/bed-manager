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

GUEST_SYSTEM = """You are AmaunaBot, a friendly booking assistant for Amauna accommodations.
Help guests check availability and book beds.
To book, collect: check-in date (YYYY-MM-DD), check-out date, full name, email — then confirm and create the booking.
Always reply in the same language the user writes in."""

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
        "name": "api_post",
        "description": "POST to bed-manager REST API. Use /bookings to create a booking, /guests to create a guest.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "body": {"type": "string"},
        }, "required": ["path", "body"]},
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
