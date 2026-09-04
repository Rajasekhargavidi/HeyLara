"""Core Pydantic schemas shared across agents and tools."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Role(str, Enum):
    ADMIN = "ADMIN"
    MARKETING = "MARKETING"
    SUPPORT = "SUPPORT"
    VIEWER = "VIEWER"


class Platform(str, Enum):
    LINKEDIN = "LINKEDIN"
    INSTAGRAM = "INSTAGRAM"
    FACEBOOK = "FACEBOOK"
    X = "X"


class AgentTask(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    agent_name: str
    input_text: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PostDraft(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    platform: Platform
    content: str
    hashtags: list[str] = Field(default_factory=list)
    status: str = "DRAFT"  # DRAFT -> WAITING_APPROVAL -> APPROVED -> PUBLISHED
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PublishedPost(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    draft_id: UUID
    platform: Platform
    provider_post_id: str
    published_at: datetime = Field(default_factory=datetime.utcnow)
    is_demo_data: bool = True


class MetricSnapshot(BaseModel):
    post_id: UUID
    reach: int
    impressions: int
    likes: int
    comments: int
    shares: int
    saves: int
    clicks: int
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    is_demo_data: bool = True


class AuditEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    actor: str
    action: str
    details: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
