"""SocialProvider contract.

Every real platform adapter (LinkedIn, Instagram, Facebook, X) implements
this interface. tools/mock/social_mock.py implements the same interface for
the zero-cost demo. Agents and the orchestrator depend only on this
interface, never on a concrete provider, so swapping mock -> real requires
no changes above this layer.
"""
from __future__ import annotations

import uuid
from typing import Protocol

from packages.schemas.models import MetricSnapshot, Platform, PublishedPost


class SocialProvider(Protocol):
    name: str

    def connect_account(self, platform: Platform) -> dict: ...

    def create_draft(self, platform: Platform, content: str, hashtags: list[str]) -> dict: ...

    def publish(
        self, draft_id: uuid.UUID, platform: Platform, content: str = "", hashtags: list[str] | None = None
    ) -> PublishedPost:
        """content/hashtags are required by real adapters (no server-side
        draft concept exists on the platform side — see tools/social/linkedin.py)
        and ignored by the mock, which already has everything it needs
        from draft_id alone."""
        ...

    def get_post(self, provider_post_id: str) -> dict: ...

    def get_metrics(self, post_id: uuid.UUID, provider_post_id: str = "") -> MetricSnapshot:
        """provider_post_id is required by real adapters to look up
        platform-side stats; the mock ignores it and fabricates DEMO DATA
        keyed only on post_id."""
        ...

    def get_comments(self, provider_post_id: str) -> list[dict]: ...

    def reply(self, provider_post_id: str, comment_id: str, text: str) -> dict: ...
