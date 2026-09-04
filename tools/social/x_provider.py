"""Real X (Twitter) adapter — Phase 12.

Implements SocialProvider against the X API v2, so agents/orchestrator
code is identical whether posting to X or any other platform.

NOT LIVE-TESTED: written against X's published API v2 docs, never
exercised against a real account — this environment has no X Developer
account or paid API tier. IMPORTANT COST NOTE: X's API is not fully free —
posting and reading at any real volume requires a paid tier (Basic/Pro).
The build spec explicitly calls this out; do not assume free-tier access
covers this adapter's needs in production.

Setup required before this can run for real:
1. Create a project + app at https://developer.x.com
2. Subscribe to at least the Basic paid tier (free tier's write limits are
   too low for regular posting, and read access is very restricted)
3. Generate OAuth 2.0 User Context credentials (needed to post as a
   specific account) or OAuth 1.0a User Context tokens
4. Set in .env: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
5. Set JARVIS_MODE=live

This adapter uses OAuth 1.0a User Context (the simpler of X's two auth
schemes for posting as a user) via `requests_oauthlib` if available.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import requests

from packages.config.settings import settings
from packages.schemas.models import MetricSnapshot, Platform, PublishedPost

BASE_URL = "https://api.twitter.com/2"


class XCapabilityUnavailable(RuntimeError):
    """Per the spec: report unavailable capabilities, never fake success."""


class XProvider:
    name = "x"

    def __init__(self) -> None:
        self.api_key = settings.x_api_key
        self.api_secret = settings.x_api_secret
        self.access_token = settings.x_access_token
        self.access_secret = settings.x_access_secret
        if not all([self.api_key, self.api_secret, self.access_token, self.access_secret]):
            raise XCapabilityUnavailable(
                "X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, and X_ACCESS_SECRET must all be set "
                "to use the real X adapter"
            )

    def _auth(self):
        try:
            from requests_oauthlib import OAuth1
        except ImportError as exc:
            raise XCapabilityUnavailable("requests_oauthlib is not installed — run `pip install requests_oauthlib`") from exc
        return OAuth1(self.api_key, self.api_secret, self.access_token, self.access_secret)

    def connect_account(self, platform: Platform) -> dict:
        resp = requests.get(f"{BASE_URL}/users/me", auth=self._auth(), timeout=15)
        if resp.status_code >= 400:
            raise XCapabilityUnavailable(f"X connect_account failed ({resp.status_code}): {resp.text}")
        return {"platform": platform, "connected": True, "account": resp.json().get("data", {}), "is_demo_data": False}

    def create_draft(self, platform: Platform, content: str, hashtags: list[str]) -> dict:
        # X has no server-side draft concept — see LinkedIn adapter's note.
        return {"platform": platform, "content": content, "hashtags": hashtags, "status": "DRAFT"}

    def publish(
        self, draft_id: uuid.UUID, platform: Platform, content: str = "", hashtags: list[str] | None = None
    ) -> PublishedPost:
        text = content
        if hashtags:
            candidate = f"{content} " + " ".join(hashtags)
            text = candidate if len(candidate) <= 280 else content[:280]
        if len(text) > 280:
            raise XCapabilityUnavailable(f"Post is {len(text)} chars, over X's 280-char limit — cannot publish as-is")

        resp = requests.post(f"{BASE_URL}/tweets", auth=self._auth(), json={"text": text}, timeout=15)
        if resp.status_code >= 400:
            raise XCapabilityUnavailable(f"X publish failed ({resp.status_code}): {resp.text}")
        tweet_id = resp.json().get("data", {}).get("id", "")
        return PublishedPost(draft_id=draft_id, platform=platform, provider_post_id=tweet_id,
                              published_at=datetime.utcnow(), is_demo_data=False)

    def get_post(self, provider_post_id: str) -> dict:
        resp = requests.get(f"{BASE_URL}/tweets/{provider_post_id}", auth=self._auth(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_metrics(self, post_id: uuid.UUID, provider_post_id: str = "") -> MetricSnapshot:
        if not provider_post_id:
            raise XCapabilityUnavailable("get_metrics requires the tweet id")
        resp = requests.get(
            f"{BASE_URL}/tweets/{provider_post_id}",
            auth=self._auth(),
            params={"tweet.fields": "public_metrics,organic_metrics"},
            timeout=15,
        )
        if resp.status_code >= 400:
            raise XCapabilityUnavailable(f"X does not expose metrics for this tweet/token combination ({resp.status_code}): {resp.text}")
        data = resp.json().get("data", {})
        # organic_metrics (impressions, profile clicks) require elevated access; public_metrics
        # (likes/retweets/replies) are the reliable baseline available at the Basic tier.
        public = data.get("public_metrics", {})
        organic = data.get("organic_metrics", {})
        return MetricSnapshot(
            post_id=post_id,
            reach=organic.get("impression_count", 0),
            impressions=organic.get("impression_count", 0),
            likes=public.get("like_count", 0),
            comments=public.get("reply_count", 0),
            shares=public.get("retweet_count", 0),
            saves=public.get("bookmark_count", 0),
            clicks=organic.get("url_link_clicks", 0),
            is_demo_data=False,
        )

    def get_comments(self, provider_post_id: str) -> list[dict]:
        resp = requests.get(
            f"{BASE_URL}/tweets/search/recent",
            auth=self._auth(),
            params={"query": f"conversation_id:{provider_post_id}", "tweet.fields": "author_id,text"},
            timeout=15,
        )
        if resp.status_code >= 400:
            raise XCapabilityUnavailable(f"Could not fetch X replies ({resp.status_code}): {resp.text}")
        return [
            {"author": t.get("author_id", ""), "text": t.get("text", ""), "is_demo_data": False}
            for t in resp.json().get("data", [])
        ]

    def reply(self, provider_post_id: str, comment_id: str, text: str) -> dict:
        resp = requests.post(
            f"{BASE_URL}/tweets", auth=self._auth(),
            json={"text": text, "reply": {"in_reply_to_tweet_id": provider_post_id}},
            timeout=15,
        )
        if resp.status_code >= 400:
            raise XCapabilityUnavailable(f"X reply failed ({resp.status_code}): {resp.text}")
        return {"replied": True, "comment_id": comment_id, "text": text, "is_demo_data": False}
