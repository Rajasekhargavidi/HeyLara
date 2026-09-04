"""EmployeeChannel contract.

Every real channel adapter (Teams, WhatsApp — email could be added the
same way via SMTP) implements this interface. The Employee/Task
Coordinator Agent depends only on this interface, never on a concrete
channel, so switching or adding channels needs no change above this layer.
"""
from __future__ import annotations

from typing import Protocol


class EmployeeChannel(Protocol):
    name: str

    def send_message(self, recipient: str, text: str) -> dict:
        """recipient is channel-specific: an AAD user id/email for Teams,
        an E.164 phone number for WhatsApp."""
        ...

    def get_recent_replies(self, recipient: str, since_message_id: str | None = None) -> list[dict]:
        ...
