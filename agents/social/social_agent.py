"""Social Media Agent — Phase 2 (Postgres/SQLite-backed).

Handles: drafting posts, requesting approval, publishing (via the Tool
Registry, never directly), and reporting metrics. Drafts/published
posts/metrics now persist through SQLAlchemy instead of the Phase 1
in-memory dicts. Command parsing is still keyword-based; a real LLM-driven
planner replaces this in Phase 4 once the Ollama adapter lands.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agents.content import content_agent
from apps.api.models_db import MetricSnapshotORM, PostDraftORM, PublishedPostORM
from packages.config.llm_provider import LLMProvider
from packages.schemas.models import Platform
from tools.registry.registry import registry

AGENT_NAME = "social_media_agent"


def create_campaign_drafts(
    db: Session,
    actor_id: str,
    topic: str,
    llm: LLMProvider,
    platforms: list[Platform] | None = None,
    variants: int = 1,
) -> list[PostDraftORM]:
    """Generate draft posts for one topic across platforms (and optionally
    multiple variants per platform) via the Content Agent/LLM."""
    platforms = platforms or [Platform.LINKEDIN]
    variants = max(1, min(variants, 3))
    drafts: list[PostDraftORM] = []

    for platform in platforms:
        posts = (
            content_agent.generate_variants(llm, topic, platform.value, variants)
            if variants > 1
            else [content_agent.generate_post_content(llm, topic, platform.value)]
        )
        for post in posts:
            result = registry.call(
                "create_post_draft",
                actor=AGENT_NAME,
                platform=platform.value,
                content=post.content,
                hashtags=post.hashtags,
            )
            if not result.ok:
                raise RuntimeError(f"create_post_draft failed: {result.error}")

            full_content = post.content
            if post.cta and post.cta not in post.content:
                full_content = f"{post.content}\n\n{post.cta}"

            draft = PostDraftORM(
                platform=platform.value,
                content=full_content,
                hashtags=post.hashtags,
                status="WAITING_APPROVAL",
                created_by=actor_id,
            )
            db.add(draft)
            drafts.append(draft)

    db.commit()
    for d in drafts:
        db.refresh(d)
    return drafts


def list_pending_approvals(db: Session) -> list[PostDraftORM]:
    return db.query(PostDraftORM).filter_by(status="WAITING_APPROVAL").all()


def approve_and_publish(db: Session, draft_id: str, actor_id: str, actor_label: str) -> PublishedPostORM:
    draft = db.get(PostDraftORM, draft_id)
    if draft is None or draft.status != "WAITING_APPROVAL":
        raise ValueError(f"No pending draft with id {draft_id}")

    result = registry.call(
        "publish_social_post",
        actor=actor_label,
        draft_id=draft_id,
        platform=draft.platform,
        content=draft.content,
        hashtags=draft.hashtags,
    )
    if not result.ok:
        raise RuntimeError(f"publish_social_post failed: {result.error}")

    output = result.output
    published = PublishedPostORM(
        id=output["id"],
        draft_id=draft_id,
        platform=draft.platform,
        provider_post_id=output["provider_post_id"],
        published_by=actor_id,
        is_demo_data=output.get("is_demo_data", True),
    )
    draft.status = "PUBLISHED"
    db.add(published)
    db.commit()
    db.refresh(published)
    return published


def report_metrics(db: Session, post_id: str) -> MetricSnapshotORM:
    published = db.get(PublishedPostORM, post_id)
    result = registry.call(
        "fetch_post_metrics",
        actor=AGENT_NAME,
        post_id=post_id,
        platform=published.platform if published else "",
        provider_post_id=published.provider_post_id if published else "",
    )
    if not result.ok:
        raise RuntimeError(f"fetch_post_metrics failed: {result.error}")

    output = result.output
    snapshot = MetricSnapshotORM(
        post_id=post_id,
        reach=output["reach"],
        impressions=output["impressions"],
        likes=output["likes"],
        comments=output["comments"],
        shares=output["shares"],
        saves=output["saves"],
        clicks=output["clicks"],
        is_demo_data=output.get("is_demo_data", True),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def list_published_posts(db: Session) -> list[PublishedPostORM]:
    return db.query(PublishedPostORM).order_by(PublishedPostORM.published_at.desc()).all()
