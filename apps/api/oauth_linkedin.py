"""LinkedIn OAuth 2.0 authorization-code flow.

Splits the flow so the parts that need your login/consent happen entirely
in your own browser (LinkedIn's domain is not something this app can or
should automate), while the parts that are just server-to-server API calls
(the code-for-token exchange, listing which orgs the resulting token can
manage) are handled here.
"""
from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

import requests

from packages.config.settings import settings

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
SCOPES = "w_organization_social r_organization_social rw_organization_admin"

# In-memory CSRF state store — fine for a single local admin flow; a
# multi-instance deployment would use a shared store (DB/Redis) instead.
_pending_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600


def create_authorization_url() -> str:
    state = secrets.token_urlsafe(24)
    _pending_states[state] = time.time() + _STATE_TTL_SECONDS
    params = {
        "response_type": "code",
        "client_id": settings.linkedin_client_id,
        "redirect_uri": settings.linkedin_redirect_uri,
        "state": state,
        "scope": SCOPES,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def validate_state(state: str) -> bool:
    expiry = _pending_states.pop(state, None)
    return expiry is not None and time.time() < expiry


def exchange_code_for_token(code: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.linkedin_redirect_uri,
            "client_id": settings.linkedin_client_id,
            "client_secret": settings.linkedin_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"LinkedIn token exchange failed ({resp.status_code}): {resp.text}")
    return resp.json()


def list_admin_organizations(access_token: str) -> list[dict]:
    """Lists organizations this token can administer, so the LaraVisionX
    page's numeric org URN can be identified without guessing."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": "202405",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    resp = requests.get(
        "https://api.linkedin.com/rest/organizationAcls",
        headers=headers,
        params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
        timeout=15,
    )
    if resp.status_code >= 400:
        return [{"error": f"Could not list organizations ({resp.status_code}): {resp.text}"}]

    elements = resp.json().get("elements", [])
    orgs = []
    for el in elements:
        org_urn = el.get("organization", "")
        org_id = org_urn.rsplit(":", 1)[-1] if org_urn else ""
        name = ""
        if org_id:
            name_resp = requests.get(
                f"https://api.linkedin.com/rest/organizations/{org_id}",
                headers=headers,
                timeout=15,
            )
            if name_resp.status_code < 400:
                name = name_resp.json().get("localizedName", "")
        orgs.append({"org_urn": org_urn, "name": name})
    return orgs
