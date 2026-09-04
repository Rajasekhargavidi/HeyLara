"""Real WhatsApp Business adapter — Phase 12.

Implements EmployeeChannel via the WhatsApp Business Cloud API (Meta) for
sending task pings to employees. Reading replies back requires Meta to
push them to a webhook JARVIS exposes — see apps/api/main.py's
/api/webhooks/whatsapp endpoint — rather than a pollable "get messages"
API, which is why get_recent_replies here reads from our own DB instead
of calling WhatsApp again.

NOT LIVE-TESTED: written against Meta's published Cloud API docs, never
exercised against a real WhatsApp Business account — this environment has
no Meta Business Manager account or verified WhatsApp Business number.

Setup required before this can run for real:
1. Create a Meta Business account and a WhatsApp Business app at
   https://developers.facebook.com/apps
2. Add a phone number (Meta provides a free test number for development,
   but sending to real employees at any volume needs a verified
   production number and passing Meta's business verification).
3. Generate a permanent access token (System User token, not the default
   24h token) for that WhatsApp Business Account.
4. Set in .env: WHATSAPP_BUSINESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID.
5. Configure a webhook (in the Meta App dashboard) pointing at
   `https://<your-domain>/api/webhooks/whatsapp` and subscribe to the
   `messages` field, so employee replies reach JARVIS.
6. Set JARVIS_MODE=live.

COST NOTE: WhatsApp Business messaging is not fully free — Meta charges
per conversation past a free tier, which varies by country. This is not a
zero-cost channel at any real volume, per the spec's own admission that
WhatsApp "has approval/cost overhead, not truly zero-cost."
"""
from __future__ import annotations

from sqlalchemy.orm import Session

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class WhatsAppCapabilityUnavailable(RuntimeError):
    pass


class WhatsAppProvider:
    name = "whatsapp"

    def __init__(self) -> None:
        from packages.config.settings import settings

        self.access_token = settings.whatsapp_business_token
        self.phone_number_id = settings.whatsapp_phone_number_id
        if not self.access_token or not self.phone_number_id:
            raise WhatsAppCapabilityUnavailable(
                "WHATSAPP_BUSINESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID must both be set "
                "to use the real WhatsApp adapter"
            )

    def send_message(self, recipient: str, text: str) -> dict:
        import requests

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,  # E.164 format, e.g. "+15551234567"
            "type": "text",
            "text": {"body": text},
        }
        resp = requests.post(
            f"{BASE_URL}/{self.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {self.access_token}"},
            json=payload,
            timeout=15,
        )
        if resp.status_code >= 400:
            raise WhatsAppCapabilityUnavailable(f"WhatsApp send_message failed ({resp.status_code}): {resp.text}")
        message_id = (resp.json().get("messages") or [{}])[0].get("id", "")
        return {"sent": True, "message_id": message_id, "is_demo_data": False}

    def get_recent_replies(self, recipient: str, since_message_id: str | None = None) -> list[dict]:
        # WhatsApp's Cloud API has no "list messages" endpoint — inbound
        # messages only arrive via the webhook (see apps/api/main.py). This
        # method reads what the webhook has already stored, rather than
        # calling out to WhatsApp again.
        raise WhatsAppCapabilityUnavailable(
            "WhatsApp has no pollable message-history API. Configure the webhook "
            "(see this module's docstring) and read replies via the EmployeeTask "
            "records the webhook populates, not via this method."
        )


def store_inbound_webhook_message(db: Session, payload: dict) -> None:
    """Parses a WhatsApp webhook payload and stores any inbound employee
    replies against the matching EmployeeTask, so they show up in the
    Employee Tasks dashboard. Called from apps/api/main.py's webhook route.
    """
    from agents.employee import employee_agent  # local import avoids a circular import at module load time

    entries = payload.get("entry", [])
    for entry in entries:
        for change in entry.get("changes", []):
            messages = change.get("value", {}).get("messages", [])
            for msg in messages:
                sender = msg.get("from", "")
                text = (msg.get("text") or {}).get("body", "")
                if sender and text:
                    employee_agent.record_inbound_reply(db, channel="whatsapp", sender=sender, text=text)
