"""Mock employee channel — zero-cost demo mode.

Used whenever real Teams/WhatsApp credentials aren't configured, so the
full "assign task -> employee responds -> status rolls up" loop can be
demonstrated without touching real accounts or costing anything.
"""
from __future__ import annotations

import random

_DEMO_REPLIES = [
    "Status: about 60% done, on track to finish by Friday.",
    "Started this today — will have an update by tomorrow EOD.",
    "Blocked on a dependency from another team, following up now.",
    "Done — ready for review.",
]


class MockEmployeeChannel:
    name = "mock"

    def send_message(self, recipient: str, text: str) -> dict:
        return {"sent": True, "recipient": recipient, "text": text, "is_demo_data": True}

    def get_recent_replies(self, recipient: str, since_message_id: str | None = None) -> list[dict]:
        return [{"id": "demo-reply-1", "from": recipient, "text": random.choice(_DEMO_REPLIES), "is_demo_data": True}]
