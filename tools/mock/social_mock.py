"""Mock SocialProvider implementation.

Implements the same interface a real LinkedIn/Instagram/Facebook/X adapter
would implement, so the orchestrator and agents never need to change when
real providers are swapped in later (see tools/social/ for that contract).

Everything here is fake and clearly labeled DEMO DATA. No network calls,
no real credentials, nothing external is touched.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime

from packages.schemas.models import MetricSnapshot, Platform, PublishedPost


class MockSocialProvider:
    """Fake social provider used for the zero-cost demo mode."""

    name = "mock"

    def __init__(self) -> None:
        self._published: dict[str, PublishedPost] = {}

    def connect_account(self, platform: Platform) -> dict:
        return {"platform": platform, "connected": True, "account": "DEMO-ACCOUNT", "is_demo_data": True}

    def create_draft(self, platform: Platform, content: str, hashtags: list[str]) -> dict:
        return {
            "platform": platform,
            "content": content,
            "hashtags": hashtags,
            "status": "DRAFT",
        }

    def publish(
        self, draft_id: uuid.UUID, platform: Platform, content: str = "", hashtags: list[str] | None = None
    ) -> PublishedPost:
        provider_post_id = f"DEMO-{platform.value}-{uuid.uuid4().hex[:10]}"
        post = PublishedPost(
            draft_id=draft_id,
            platform=platform,
            provider_post_id=provider_post_id,
            published_at=datetime.utcnow(),
            is_demo_data=True,
        )
        self._published[str(post.id)] = post
        return post

    def get_post(self, provider_post_id: str) -> dict:
        return {"provider_post_id": provider_post_id, "status": "PUBLISHED", "is_demo_data": True}

    def get_metrics(self, post_id: uuid.UUID, provider_post_id: str = "") -> MetricSnapshot:
        return MetricSnapshot(
            post_id=post_id,
            reach=random.randint(150, 2500),
            impressions=random.randint(300, 5000),
            likes=random.randint(5, 200),
            comments=random.randint(0, 40),
            shares=random.randint(0, 25),
            saves=random.randint(0, 15),
            clicks=random.randint(0, 60),
            is_demo_data=True,
        )

    def get_comments(self, provider_post_id: str) -> list[dict]:
        return [
            {"author": "demo_user_1", "text": "Great post!", "is_demo_data": True},
            {"author": "demo_user_2", "text": "Can you share the source?", "is_demo_data": True},
        ]

    def reply(self, provider_post_id: str, comment_id: str, text: str) -> dict:
        return {"replied": True, "comment_id": comment_id, "text": text, "is_demo_data": True}
