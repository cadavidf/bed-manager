from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.services.whatsapp_bot import handle_message

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.get("/webhook")
async def verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive(request: Request):
    body = await request.json()
    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                messages = change.get("value", {}).get("messages", [])
                for msg in messages:
                    phone = msg["from"]
                    if msg["type"] == "text":
                        text = msg["text"]["body"]
                    elif msg["type"] == "interactive":
                        inter = msg["interactive"]
                        if inter["type"] == "button_reply":
                            text = inter["button_reply"]["id"]
                        elif inter["type"] == "list_reply":
                            text = inter["list_reply"]["id"]
                        else:
                            continue
                    else:
                        continue
                    await handle_message(phone, text)
    except Exception:
        pass  # always return 200 so Meta doesn't retry
    return {"status": "ok"}
