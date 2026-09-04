"""Real Microsoft Teams adapter — Phase 12.

Implements EmployeeChannel via the Microsoft Graph API, using an app-only
(client credentials) token to send and read 1:1 chat messages with an
employee. This is real two-way capability, not a one-way webhook notifier
— required because the original ask was "get updates from employees" too,
not just ping them.

NOT LIVE-TESTED: written against Microsoft Graph's published docs, never
exercised against a real tenant — this environment has no Azure AD tenant
or admin access to register an app in it.

Setup required before this can run for real:
1. Register an app in Azure AD (portal.azure.com > App registrations).
2. Grant it Microsoft Graph APPLICATION permissions: `Chat.Create`,
   `ChatMessage.Send`, `ChatMessage.Read.All` — these require a Global
   Administrator's consent (admin-only, cannot be self-approved).
3. Create a client secret for the app.
4. Set in .env: TEAMS_TENANT_ID, TEAMS_CLIENT_ID, TEAMS_CLIENT_SECRET.
5. Set JARVIS_MODE=live.

Employees are addressed by their Azure AD user id or userPrincipalName
(their email in most tenants) — pass that as `recipient`.
"""
from __future__ import annotations

import time

import requests

from packages.config.settings import settings

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class TeamsCapabilityUnavailable(RuntimeError):
    pass


class TeamsProvider:
    name = "teams"

    def __init__(self) -> None:
        self.tenant_id = settings.teams_tenant_id
        self.client_id = settings.teams_client_id
        self.client_secret = settings.teams_client_secret
        if not all([self.tenant_id, self.client_id, self.client_secret]):
            raise TeamsCapabilityUnavailable(
                "TEAMS_TENANT_ID, TEAMS_CLIENT_ID, and TEAMS_CLIENT_SECRET must all be set "
                "to use the real Teams adapter"
            )
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = requests.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            raise TeamsCapabilityUnavailable(f"Teams/Graph auth failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"}

    def _get_or_create_chat(self, recipient_user_id: str) -> str:
        # A 1:1 chat requires the bot/app's own service-principal id as a
        # member alongside the employee — Graph's oneOnOne chat creation.
        payload = {
            "chatType": "oneOnOne",
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{recipient_user_id}')",
                },
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{self.client_id}')",
                },
            ],
        }
        resp = requests.post(f"{GRAPH_BASE_URL}/chats", headers=self._headers(), json=payload, timeout=15)
        if resp.status_code >= 400:
            raise TeamsCapabilityUnavailable(f"Could not create/find Teams chat ({resp.status_code}): {resp.text}")
        return resp.json()["id"]

    def send_message(self, recipient: str, text: str) -> dict:
        chat_id = self._get_or_create_chat(recipient)
        resp = requests.post(
            f"{GRAPH_BASE_URL}/chats/{chat_id}/messages",
            headers=self._headers(),
            json={"body": {"content": text}},
            timeout=15,
        )
        if resp.status_code >= 400:
            raise TeamsCapabilityUnavailable(f"Teams send_message failed ({resp.status_code}): {resp.text}")
        return {"sent": True, "chat_id": chat_id, "message_id": resp.json().get("id"), "is_demo_data": False}

    def get_recent_replies(self, recipient: str, since_message_id: str | None = None) -> list[dict]:
        chat_id = self._get_or_create_chat(recipient)
        resp = requests.get(f"{GRAPH_BASE_URL}/chats/{chat_id}/messages", headers=self._headers(), timeout=15)
        if resp.status_code >= 400:
            raise TeamsCapabilityUnavailable(f"Teams get_recent_replies failed ({resp.status_code}): {resp.text}")
        messages = resp.json().get("value", [])
        if since_message_id:
            ids = [m["id"] for m in messages]
            if since_message_id in ids:
                messages = messages[: ids.index(since_message_id)]
        return [
            {"id": m["id"], "from": m.get("from", {}).get("user", {}).get("displayName", ""),
             "text": m.get("body", {}).get("content", ""), "is_demo_data": False}
            for m in messages
        ]
