"""Real LinkedIn adapter — Phase 12.

Implements the same SocialProvider interface as tools/mock/social_mock.py
against LinkedIn's actual REST API (Posts API, 2023+ version), so agents
and the orchestrator never need to know whether they're talking to the
mock or the real thing.

NOT LIVE-TESTED: this was written against LinkedIn's published API
documentation but never exercised against a real LinkedIn account,
because doing so requires a LinkedIn Developer app, Marketing Developer
Platform / Community Management API access approval, and an organization
admin's OAuth token — none of which this environment has. Treat this as
"ready to activate," not "verified."

Setup required before this can run for real:
1. Create a LinkedIn Developer app at https://www.linkedin.com/developers/
2. Request the "Community Management API" product (needed for organization
   posting) and get it approved — this is a manual LinkedIn review step.
3. Complete the OAuth 2.0 flow for a user who is an admin of the target
   LinkedIn Company Page, requesting the `w_organization_social` and
   `r_organization_social` scopes.
4. Set in .env: LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET,
   LINKEDIN_ACCESS_TOKEN (the token from step 3), LINKEDIN_ORG_URN
   (e.g. "urn:li:organization:12345678").
5. Set JARVIS_MODE=live — see tools/registry/bootstrap.py for how the
   registry picks this adapter over the mock once credentials are present.

API version pinned via LinkedIn-Version header — LinkedIn requires this
and versions are dated; update LINKEDIN_API_VERSION as LinkedIn deprecates
old versions (they give ~1 year notice per their versioning policy).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import requests

from packages.config.settings import settings
from packages.schemas.models import MetricSnapshot, Platform, PublishedPost

LINKEDIN_API_VERSION = "202405"  # bump per LinkedIn's versioning schedule
BASE_URL = "https://api.linkedin.com/rest"


class LinkedInCapabilityUnavailable(RuntimeError):
    """Raised when LinkedIn's API cannot perform the requested action.

    Per the spec: 'If an API cannot perform a requested action, clearly
    report it instead of simulating success.' Callers must surface this,
    never swallow it into a fake success.
    """


class LinkedInProvider:
    name = "linkedin"

    def __init__(self) -> None:
        self.access_token = settings.linkedin_access_token
        self.org_urn = settings.linkedin_org_urn
        if not self.access_token or not self.org_urn:
            raise LinkedInCapabilityUnavailable(
                "LINKEDIN_ACCESS_TOKEN and LINKEDIN_ORG_URN must be set to use the real LinkedIn adapter"
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "LinkedIn-Version": LINKEDIN_API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def connect_account(self, platform: Platform) -> dict:
        resp = requests.get(f"{BASE_URL}/organizationAcls", headers=self._headers(),
                             params={"q": "roleAssignee"}, timeout=15)
        resp.raise_for_status()
        return {"platform": platform, "connected": True, "org_urn": self.org_urn, "is_demo_data": False}

    def create_draft(self, platform: Platform, content: str, hashtags: list[str]) -> dict:
        # LinkedIn's API has no server-side draft concept — the draft
        # exists only in our own DB (PostDraftORM) until publish() is
        # called. This mirrors the mock's behavior: create_draft is a
        # local no-op from the API's point of view.
        return {"platform": platform, "content": content, "hashtags": hashtags, "status": "DRAFT"}

    def publish(self, draft_id: uuid.UUID, platform: Platform, content: str = "", hashtags: list[str] | None = None) -> PublishedPost:
        body_text = content
        if hashtags:
            body_text = f"{content}\n\n" + " ".join(hashtags)

        payload = {
            "author": self.org_urn,
            "commentary": body_text,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        resp = requests.post(f"{BASE_URL}/posts", headers=self._headers(), json=payload, timeout=15)
        if resp.status_code >= 400:
            raise LinkedInCapabilityUnavailable(f"LinkedIn publish failed ({resp.status_code}): {resp.text}")

        # LinkedIn returns the new post's URN in the x-restli-id response header.
        post_urn = resp.headers.get("x-restli-id", "")
        return PublishedPost(
            draft_id=draft_id,
            platform=platform,
            provider_post_id=post_urn,
            published_at=datetime.utcnow(),
            is_demo_data=False,
        )

    def get_post(self, provider_post_id: str) -> dict:
        resp = requests.get(f"{BASE_URL}/posts/{provider_post_id}", headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_metrics(self, post_id: uuid.UUID, provider_post_id: str = "") -> MetricSnapshot:
        if not provider_post_id:
            raise LinkedInCapabilityUnavailable("get_metrics requires the LinkedIn post URN")
        # Organic Social Metrics API — https://learn.microsoft.com/linkedin/marketing/community-management/shares/share-statistics
        resp = requests.get(
            f"{BASE_URL}/organizationalEntityShareStatistics",
            headers=self._headers(),
            params={"q": "organizationalEntity", "organizationalEntity": self.org_urn, "shares[0]": provider_post_id},
            timeout=15,
        )
        if resp.status_code >= 400:
            raise LinkedInCapabilityUnavailable(
                f"LinkedIn does not expose per-post statistics for this token/tier ({resp.status_code}): {resp.text}"
            )
        stats = (resp.json().get("elements") or [{}])[0].get("totalShareStatistics", {})
        return MetricSnapshot(
            post_id=post_id,
            reach=stats.get("impressionCount", 0),
            impressions=stats.get("impressionCount", 0),
            likes=stats.get("likeCount", 0),
            comments=stats.get("commentCount", 0),
            shares=stats.get("shareCount", 0),
            saves=0,  # LinkedIn's API does not expose a "saves" metric — report 0, never invent one
            clicks=stats.get("clickCount", 0),
            is_demo_data=False,
        )

    def get_comments(self, provider_post_id: str) -> list[dict]:
        resp = requests.get(f"{BASE_URL}/socialActions/{provider_post_id}/comments", headers=self._headers(), timeout=15)
        if resp.status_code >= 400:
            raise LinkedInCapabilityUnavailable(f"Could not fetch LinkedIn comments ({resp.status_code}): {resp.text}")
        return [
            {"author": c.get("actor", ""), "text": c.get("message", {}).get("text", ""), "is_demo_data": False}
            for c in resp.json().get("elements", [])
        ]

    def reply(self, provider_post_id: str, comment_id: str, text: str) -> dict:
        payload = {"actor": self.org_urn, "object": provider_post_id, "message": {"text": text}}
        resp = requests.post(
            f"{BASE_URL}/socialActions/{provider_post_id}/comments", headers=self._headers(), json=payload, timeout=15
        )
        if resp.status_code >= 400:
            raise LinkedInCapabilityUnavailable(f"LinkedIn reply failed ({resp.status_code}): {resp.text}")
        return {"replied": True, "comment_id": comment_id, "text": text, "is_demo_data": False}
