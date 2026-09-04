"""Wires concrete tool implementations into the shared ToolRegistry.

Phase 1-11 only registered the mock social provider. Phase 12 adds real
LinkedIn/Meta/X adapters (tools/social/) that activate automatically once
JARVIS_MODE=live and the relevant credentials are set — otherwise every
call transparently falls back to the mock, per the spec's "mark the
capability as unavailable and show a manual fallback" rule. Agents never
need to know which one they got.
"""
from __future__ import annotations

import logging
import uuid

from packages.config.settings import settings
from packages.schemas.models import Platform
from tools.mock.social_mock import MockSocialProvider
from tools.registry.registry import registry

logger = logging.getLogger("jarvis.bootstrap")

_mock_provider = MockSocialProvider()


def _get_social_provider(platform: Platform):
    """Returns (provider, is_real). Falls back to the mock — and logs why —
    whenever real mode isn't configured or the real adapter can't init."""
    if settings.jarvis_mode == "live":
        try:
            if platform == Platform.LINKEDIN:
                from tools.social.linkedin import LinkedInProvider
                return LinkedInProvider(), True
            if platform in (Platform.INSTAGRAM, Platform.FACEBOOK):
                from tools.social.meta import MetaProvider
                return MetaProvider(), True
            if platform == Platform.X:
                from tools.social.x_provider import XProvider
                return XProvider(), True
        except RuntimeError as exc:
            logger.warning("Real %s provider unavailable, falling back to mock: %s", platform.value, exc)
    return _mock_provider, False


def _create_post_draft(platform: str, content: str, hashtags: list[str] | None = None) -> dict:
    provider, _ = _get_social_provider(Platform(platform))
    return provider.create_draft(Platform(platform), content, hashtags or [])


def _publish_social_post(draft_id: str, platform: str, content: str = "", hashtags: list[str] | None = None) -> dict:
    # If the real adapter is configured but the platform call itself fails
    # (rate limit, permission, content policy, etc.), the RuntimeError
    # propagates up rather than silently falling back to the mock — a
    # fallback here would misrepresent a real publish attempt as having
    # succeeded via a fake ID.
    provider, is_real = _get_social_provider(Platform(platform))
    post = provider.publish(
        uuid.UUID(draft_id) if _is_uuid(draft_id) else uuid.uuid4(),
        Platform(platform), content=content, hashtags=hashtags or [],
    )
    result = post.model_dump(mode="json")
    result["provider_is_real"] = is_real
    return result


def _fetch_post_metrics(post_id: str, platform: str = "", provider_post_id: str = "") -> dict:
    provider, is_real = _get_social_provider(Platform(platform)) if platform else (_mock_provider, False)
    snapshot = provider.get_metrics(
        uuid.UUID(post_id) if _is_uuid(post_id) else uuid.uuid4(), provider_post_id=provider_post_id
    )
    result = snapshot.model_dump(mode="json")
    result["provider_is_real"] = is_real
    return result


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _search_knowledge(query: str) -> dict:
    # Marker tool for the Tool Registry allow-list + audit log. The real
    # retrieval (embedding + permission-filtered similarity search) needs a
    # DB session and the caller's role, so it runs in
    # agents/knowledge/knowledge_agent.answer_from_knowledge; this call
    # exists purely so the action is allow-listed and audited like every
    # other tool.
    return {"query": query}


def _ingest_document(title: str, source: str) -> dict:
    return {"title": title, "source": source}


def _search_web_or_sources(query: str) -> dict:
    # Marker tool for allow-listing + audit; the real search call lives in
    # tools/research/web_search.py (called directly by technology_agent so
    # it can return typed SearchResult objects, not just an audit dict).
    return {"query": query}


def _list_customer_messages() -> dict:
    return {}


def _draft_customer_reply(message_id: str) -> dict:
    return {"message_id": message_id}


def _send_customer_reply(message_id: str) -> dict:
    return {"message_id": message_id}


def _create_lead(conversation_id: str) -> dict:
    return {"conversation_id": conversation_id}


def _generate_report(period: str) -> dict:
    return {"period": period}


def _assign_employee_task(employee_id: str, description: str, channel: str) -> dict:
    return {"employee_id": employee_id, "channel": channel}


def _request_employee_status_update(employee_id: str, channel: str) -> dict:
    return {"employee_id": employee_id, "channel": channel}


def bootstrap_tools() -> None:
    if registry.is_registered("create_post_draft"):
        return  # already bootstrapped (e.g. re-imported in tests)

    registry.register("create_post_draft", _create_post_draft, requires_approval=False)
    registry.register("publish_social_post", _publish_social_post, requires_approval=True)
    registry.register("fetch_post_metrics", _fetch_post_metrics, requires_approval=False)
    registry.register("search_knowledge", _search_knowledge, requires_approval=False)
    registry.register("ingest_document", _ingest_document, requires_approval=False)
    registry.register("search_web_or_sources", _search_web_or_sources, requires_approval=False)
    registry.register("list_customer_messages", _list_customer_messages, requires_approval=False)
    registry.register("draft_customer_reply", _draft_customer_reply, requires_approval=False)
    registry.register("send_customer_reply", _send_customer_reply, requires_approval=True)
    registry.register("create_lead", _create_lead, requires_approval=False)
    registry.register("generate_report", _generate_report, requires_approval=False)
    registry.register("assign_employee_task", _assign_employee_task, requires_approval=False)
    registry.register("request_employee_status_update", _request_employee_status_update, requires_approval=False)
