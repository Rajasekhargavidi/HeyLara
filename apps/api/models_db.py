"""SQLAlchemy ORM models — Phase 2 persistence.

Replaces the in-memory dicts used in Phase 1 for users, drafts, published
posts, metrics, and the audit log.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PostDraftORM(Base):
    __tablename__ = "post_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PublishedPostORM(Base):
    __tablename__ = "published_posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    draft_id: Mapped[str] = mapped_column(String(36), ForeignKey("post_drafts.id"))
    platform: Mapped[str] = mapped_column(String(32))
    provider_post_id: Mapped[str] = mapped_column(String(128))
    published_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=True)


class MetricSnapshotORM(Base):
    __tablename__ = "metric_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(String(36), ForeignKey("published_posts.id"))
    reach: Mapped[int] = mapped_column(Integer)
    impressions: Mapped[int] = mapped_column(Integer)
    likes: Mapped[int] = mapped_column(Integer)
    comments: Mapped[int] = mapped_column(Integer)
    shares: Mapped[int] = mapped_column(Integer)
    saves: Mapped[int] = mapped_column(Integer)
    clicks: Mapped[int] = mapped_column(Integer)
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeDocumentORM(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(255))  # original filename or source label
    access_role: Mapped[str] = mapped_column(String(32), default="VIEWER")  # minimum role required to read it
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeChunkORM(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_documents.id"))
    section: Mapped[str] = mapped_column(String(64))  # e.g. "chunk 3"
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON)  # list[float] — no pgvector available, so
    # similarity is computed in Python (tools/knowledge/vector_store.py). Swapping to a real
    # pgvector column + SQL similarity search is a drop-in change once Postgres+pgvector is
    # confirmed available, without touching the RAG agent's interface.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TechnologyUpdateORM(Base):
    __tablename__ = "technology_updates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # dedup key: sha256(title+url)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(255))  # domain the item came from
    topic: Mapped[str] = mapped_column(String(128))  # which briefing topic surfaced it
    what_changed: Mapped[str] = mapped_column(Text)
    why_care: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))  # LOW/MEDIUM/HIGH — the model's confidence in its own summary
    rank: Mapped[str] = mapped_column(String(16))  # LOW/MEDIUM/HIGH — importance to LaraVisionX
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CustomerConversationORM(Base):
    __tablename__ = "customer_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String(32))  # LINKEDIN/INSTAGRAM/FACEBOOK/X/DEMO
    customer_handle: Mapped[str] = mapped_column(String(255))
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CustomerMessageORM(Base):
    __tablename__ = "customer_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("customer_conversations.id"))
    sender: Mapped[str] = mapped_column(String(16))  # "customer" or "jarvis"
    content: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(32), nullable=True)  # SALES/SUPPORT/PARTNERSHIP/COMPLAINT/SPAM/OTHER
    status: Mapped[str] = mapped_column(String(32), default="NEW")  # NEW/DRAFTED/ESCALATED/RESOLVED
    draft_reply: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LeadORM(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("customer_conversations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    contact: Mapped[str] = mapped_column(String(255), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EmployeeORM(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    teams_user_id: Mapped[str] = mapped_column(String(255), nullable=True)  # Azure AD user id/UPN
    whatsapp_number: Mapped[str] = mapped_column(String(32), nullable=True)  # E.164
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EmployeeTaskORM(Base):
    __tablename__ = "employee_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"))
    description: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(16))  # teams/whatsapp/mock
    status: Mapped[str] = mapped_column(String(32), default="ASSIGNED")  # ASSIGNED/IN_PROGRESS/BLOCKED/DONE
    latest_update: Mapped[str] = mapped_column(Text, nullable=True)  # most recent status text from the employee
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditEventORM(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(255))
    tool: Mapped[str] = mapped_column(String(128))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str] = mapped_column(String(1024), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
