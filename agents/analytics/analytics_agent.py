"""Analytics Agent — Phase 10.

Aggregates confirmed metrics only, compares against the previous period
when there's enough history to do so, and identifies top-performing
content without claiming causation it can't support — per the ANALYTICS
PROMPT in the master build spec. Also assembles the CEO weekly/daily
report by pulling real counts from every other agent's stored data —
never inventing a number that isn't backed by a query.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.models_db import (
    AuditEventORM,
    CustomerMessageORM,
    LeadORM,
    MetricSnapshotORM,
    PostDraftORM,
    PublishedPostORM,
    TechnologyUpdateORM,
)
from packages.config.llm_provider import LLMProvider
from tools.registry.registry import registry

AGENT_NAME = "analytics_agent"

METRIC_FIELDS = ("reach", "impressions", "likes", "comments", "shares", "saves", "clicks")


def _period_bounds(period: str) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (current_start, current_end, previous_start, previous_end)."""
    now = datetime.utcnow()
    days = 1 if period == "today" else 7
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)
    return current_start, now, previous_start, current_start


def get_metrics_summary(db: Session, period: str = "weekly") -> dict:
    current_start, current_end, previous_start, previous_end = _period_bounds(period)

    def _totals(start: datetime, end: datetime) -> dict:
        rows = (
            db.query(MetricSnapshotORM)
            .filter(MetricSnapshotORM.captured_at >= start, MetricSnapshotORM.captured_at < end)
            .all()
        )
        totals = {field: sum(getattr(r, field) for r in rows) for field in METRIC_FIELDS}
        totals["post_count"] = len(rows)
        totals["is_demo_data"] = all(r.is_demo_data for r in rows) if rows else True
        return totals

    current = _totals(current_start, current_end)
    previous = _totals(previous_start, previous_end)

    comparison = {}
    has_previous_data = previous["post_count"] > 0
    for field in METRIC_FIELDS:
        if has_previous_data and previous[field] > 0:
            change_pct = round(((current[field] - previous[field]) / previous[field]) * 100, 1)
            comparison[field] = f"{'+' if change_pct >= 0 else ''}{change_pct}% vs previous period"
        else:
            comparison[field] = "insufficient prior-period data for comparison"

    return {"period": period, "current": current, "previous": previous, "comparison": comparison}


def identify_top_performing(db: Session, limit: int = 1) -> list[dict]:
    """Rank published posts by a simple engagement score (their most recent
    snapshot). Reports only what the numbers show — never claims *why* a
    post performed well without evidence, per the spec's "do not claim
    causation without evidence" rule."""
    rows = (
        db.query(PublishedPostORM, MetricSnapshotORM)
        .join(MetricSnapshotORM, MetricSnapshotORM.post_id == PublishedPostORM.id)
        .order_by(MetricSnapshotORM.captured_at.desc())
        .all()
    )
    # Keep only the latest snapshot per post.
    latest_by_post: dict[str, tuple] = {}
    for post, snap in rows:
        if post.id not in latest_by_post:
            latest_by_post[post.id] = (post, snap)

    scored = []
    for post, snap in latest_by_post.values():
        engagement_score = snap.likes + snap.comments * 2 + snap.shares * 3 + snap.saves * 2
        scored.append((engagement_score, post, snap))
    scored.sort(key=lambda t: t[0], reverse=True)

    results = []
    for score, post, snap in scored[:limit]:
        results.append({
            "post_id": post.id,
            "platform": post.platform,
            "provider_post_id": post.provider_post_id,
            "engagement_score": score,
            "reach": snap.reach,
            "likes": snap.likes,
            "comments": snap.comments,
            "shares": snap.shares,
            "is_demo_data": snap.is_demo_data,
            "observation": (
                f"Highest engagement score among {len(scored)} published post(s) with recorded metrics. "
                "Sample size is too small to attribute this to any specific content driver."
                if len(scored) <= 3 else
                "Highest engagement score this period."
            ),
        })
    return results


def count(db: Session, model, **filters) -> int:
    query = db.query(func.count()).select_from(model)
    for key, value in filters.items():
        query = query.filter(getattr(model, key) == value)
    return query.scalar() or 0


def build_ceo_report(db: Session, llm: LLMProvider, period: str = "weekly") -> dict:
    registry.call("generate_report", actor=AGENT_NAME, period=period)
    current_start, current_end, _, _ = _period_bounds(period)

    tech_needing_attention = count(db, TechnologyUpdateORM, rank="HIGH")
    pending_approvals = count(db, PostDraftORM, status="WAITING_APPROVAL")
    published_posts = (
        db.query(func.count()).select_from(PublishedPostORM)
        .filter(PublishedPostORM.published_at >= current_start).scalar() or 0
    )
    new_leads = (
        db.query(func.count()).select_from(LeadORM)
        .filter(LeadORM.created_at >= current_start).scalar() or 0
    )
    conversations_needing_attention = (
        db.query(func.count()).select_from(CustomerMessageORM)
        .filter(CustomerMessageORM.status.in_(["NEW", "ESCALATED"])).scalar() or 0
    )
    agent_failures = (
        db.query(func.count()).select_from(AuditEventORM)
        .filter(AuditEventORM.ok.is_(False), AuditEventORM.created_at >= current_start).scalar() or 0
    )

    metrics = get_metrics_summary(db, period)
    top_posts = identify_top_performing(db, limit=3)

    facts = (
        f"Period: {period}\n"
        f"Technology updates rated HIGH importance, awaiting review: {tech_needing_attention}\n"
        f"Social posts waiting for approval: {pending_approvals}\n"
        f"Posts published this period: {published_posts}\n"
        f"New leads captured this period: {new_leads}\n"
        f"Customer conversations needing attention (new or escalated): {conversations_needing_attention}\n"
        f"Agent tool-call failures this period: {agent_failures}\n"
        f"Total reach this period: {metrics['current']['reach']} ({metrics['comparison']['reach']})\n"
        f"Total engagement (likes+comments+shares) this period: "
        f"{metrics['current']['likes'] + metrics['current']['comments'] + metrics['current']['shares']}\n"
    )

    system_prompt = (
        "You are Laraon writing the recommendations section of a CEO report for LaraVisionX. "
        "You are given ONLY confirmed numbers below — use ONLY these facts, do not invent any "
        "other numbers, customers, or outcomes. Do not claim a metric change was CAUSED by any "
        "specific action unless the facts explicitly say so. If a number is 0 or missing, say so "
        "plainly rather than guessing. Write 2-4 short, concrete recommendations as a plain list."
    )
    try:
        recommendations = llm.generate(facts, system=system_prompt).strip()
    except RuntimeError as exc:
        recommendations = f"Could not generate recommendations — local LLM unreachable ({exc})."

    return {
        "period": period,
        "technology_updates_needing_attention": tech_needing_attention,
        "posts_waiting_for_approval": pending_approvals,
        "published_posts_this_period": published_posts,
        "social_metrics": metrics,
        "top_performing_posts": top_posts,
        "new_leads_this_period": new_leads,
        "customer_conversations_needing_attention": conversations_needing_attention,
        "agent_failures_this_period": agent_failures,
        "recommendations": recommendations,
    }
