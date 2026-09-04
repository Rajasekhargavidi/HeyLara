"""Real Meta (Instagram + Facebook) adapter — Phase 12.

Implements SocialProvider against Meta's Graph API for both Instagram
Business accounts and Facebook Pages, so the orchestrator/agents don't
need a separate code path per Meta platform.

NOT LIVE-TESTED: written against Meta's published Graph API docs, never
exercised against a real account — this environment has no Meta Business
account, app review approval, or long-lived Page/IG access token.

Setup required before this can run for real:
1. Create a Meta app at https://developers.facebook.com/apps
2. Add the "Instagram Graph API" and/or "Facebook Login for Business"
   products; for Instagram you need a Business or Creator account linked
   to a Facebook Page.
3. Complete Meta's App Review for the `pages_manage_posts`,
   `pages_read_engagement`, `instagram_basic`, and
   `instagram_content_publish` permissions — this is a manual review Meta
   performs and can take days to weeks.
4. Generate a long-lived Page access token (Meta's tokens default to
   short-lived; exchange via the /oauth/access_token endpoint with
   fb_exchange_token).
5. Set in .env: FACEBOOK_ACCESS_TOKEN (also used for Instagram — Meta's
   Instagram Graph API is authenticated via the linked Page's token),
   FACEBOOK_PAGE_ID, INSTAGRAM_BUSINESS_ACCOUNT_ID.
6. Set JARVIS_MODE=live.

Instagram's publish flow is two-step (create a media container, then
publish it) — this is Meta's actual API design, not a JARVIS limitation.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime

import requests

from packages.config.settings import settings
from packages.schemas.models import MetricSnapshot, Platform, PublishedPost

GRAPH_API_VERSION = "v21.0"  # bump per Meta's deprecation schedule (~2 years per version)
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class MetaCapabilityUnavailable(RuntimeError):
    """Per the spec: report unavailable capabilities, never fake success."""


class MetaProvider:
    name = "meta"

    def __init__(self) -> None:
        self.access_token = settings.facebook_access_token
        self.page_id = settings.facebook_page_id
        self.ig_account_id = settings.instagram_business_account_id
        if not self.access_token:
            raise MetaCapabilityUnavailable("FACEBOOK_ACCESS_TOKEN must be set to use the real Meta adapter")

    def _params(self, **extra) -> dict:
        return {"access_token": self.access_token, **extra}

    def connect_account(self, platform: Platform) -> dict:
        node_id = self.ig_account_id if platform == Platform.INSTAGRAM else self.page_id
        if not node_id:
            raise MetaCapabilityUnavailable(f"No account id configured for {platform.value}")
        resp = requests.get(f"{BASE_URL}/{node_id}", params=self._params(fields="id,name"), timeout=15)
        resp.raise_for_status()
        return {"platform": platform, "connected": True, "account_id": node_id, "is_demo_data": False}

    def create_draft(self, platform: Platform, content: str, hashtags: list[str]) -> dict:
        # No server-side draft concept on Meta's side either — see LinkedIn adapter's note.
        return {"platform": platform, "content": content, "hashtags": hashtags, "status": "DRAFT"}

    def publish(
        self, draft_id: uuid.UUID, platform: Platform, content: str = "", hashtags: list[str] | None = None,
        image_url: str | None = None,
    ) -> PublishedPost:
        message = content
        if hashtags:
            message = f"{content}\n\n" + " ".join(hashtags)

        if platform == Platform.FACEBOOK:
            if not self.page_id:
                raise MetaCapabilityUnavailable("FACEBOOK_PAGE_ID is not configured")
            resp = requests.post(f"{BASE_URL}/{self.page_id}/feed", params=self._params(message=message), timeout=15)
            if resp.status_code >= 400:
                raise MetaCapabilityUnavailable(f"Facebook publish failed ({resp.status_code}): {resp.text}")
            post_id = resp.json().get("id", "")

        elif platform == Platform.INSTAGRAM:
            if not self.ig_account_id:
                raise MetaCapabilityUnavailable("INSTAGRAM_BUSINESS_ACCOUNT_ID is not configured")
            if not image_url:
                # Instagram's API requires a hosted image/video URL for every post —
                # it cannot publish text-only content, unlike Facebook/LinkedIn/X.
                raise MetaCapabilityUnavailable(
                    "Instagram publishing requires an image_url (Instagram has no text-only post type). "
                    "Report this to the user rather than simulating a text-only post."
                )
            container = requests.post(
                f"{BASE_URL}/{self.ig_account_id}/media",
                params=self._params(image_url=image_url, caption=message),
                timeout=15,
            )
            if container.status_code >= 400:
                raise MetaCapabilityUnavailable(f"Instagram media container failed ({container.status_code}): {container.text}")
            creation_id = container.json()["id"]

            time.sleep(2)  # Meta's API needs a moment to process the container before publishing
            publish_resp = requests.post(
                f"{BASE_URL}/{self.ig_account_id}/media_publish",
                params=self._params(creation_id=creation_id),
                timeout=15,
            )
            if publish_resp.status_code >= 400:
                raise MetaCapabilityUnavailable(f"Instagram publish failed ({publish_resp.status_code}): {publish_resp.text}")
            post_id = publish_resp.json().get("id", "")

        else:
            raise MetaCapabilityUnavailable(f"MetaProvider does not handle platform {platform.value}")

        return PublishedPost(draft_id=draft_id, platform=platform, provider_post_id=post_id,
                              published_at=datetime.utcnow(), is_demo_data=False)

    def get_post(self, provider_post_id: str) -> dict:
        resp = requests.get(f"{BASE_URL}/{provider_post_id}", params=self._params(fields="id,permalink_url"), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_metrics(self, post_id: uuid.UUID, provider_post_id: str = "") -> MetricSnapshot:
        if not provider_post_id:
            raise MetaCapabilityUnavailable("get_metrics requires the Meta post/media id")
        # Field set differs between FB post insights and IG media insights;
        # try IG's field names first, then fall back to FB's.
        resp = requests.get(
            f"{BASE_URL}/{provider_post_id}/insights",
            params=self._params(metric="impressions,reach,likes,comments,shares,saved"),
            timeout=15,
        )
        if resp.status_code >= 400:
            raise MetaCapabilityUnavailable(
                f"Meta does not expose insights for this post/token combination ({resp.status_code}): {resp.text}"
            )
        values = {d["name"]: d["values"][0]["value"] for d in resp.json().get("data", [])}
        return MetricSnapshot(
            post_id=post_id,
            reach=values.get("reach", 0),
            impressions=values.get("impressions", 0),
            likes=values.get("likes", 0),
            comments=values.get("comments", 0),
            shares=values.get("shares", 0),
            saves=values.get("saved", 0),
            clicks=0,  # Meta does not expose organic post click-through as a standard insight metric
            is_demo_data=False,
        )

    def get_comments(self, provider_post_id: str) -> list[dict]:
        resp = requests.get(f"{BASE_URL}/{provider_post_id}/comments", params=self._params(), timeout=15)
        if resp.status_code >= 400:
            raise MetaCapabilityUnavailable(f"Could not fetch Meta comments ({resp.status_code}): {resp.text}")
        return [
            {"author": c.get("from", {}).get("name", ""), "text": c.get("message", ""), "is_demo_data": False}
            for c in resp.json().get("data", [])
        ]

    def reply(self, provider_post_id: str, comment_id: str, text: str) -> dict:
        resp = requests.post(f"{BASE_URL}/{comment_id}/comments", params=self._params(message=text), timeout=15)
        if resp.status_code >= 400:
            raise MetaCapabilityUnavailable(f"Meta reply failed ({resp.status_code}): {resp.text}")
        return {"replied": True, "comment_id": comment_id, "text": text, "is_demo_data": False}
