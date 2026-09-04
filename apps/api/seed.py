"""Seeds default demo users and a demo knowledge document.

Passwords and knowledge content are for local demo use only.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.auth import hash_password
from apps.api.models_db import KnowledgeDocumentORM, UserORM
from packages.schemas.models import Role

DEMO_USERS = [
    ("admin@laravisionx.com", "admin123", Role.ADMIN),
    ("marketing@laravisionx.com", "marketing123", Role.MARKETING),
    ("support@laravisionx.com", "support123", Role.SUPPORT),
    ("viewer@laravisionx.com", "viewer123", Role.VIEWER),
]

DEMO_KNOWLEDGE_TITLE = "LaraVisionX Company Overview (DEMO)"

DEMO_KNOWLEDGE_TEXT = """\
LaraVisionX Company Overview — DEMO KNOWLEDGE DOCUMENT

This is a placeholder document seeded for Phase 5 demo purposes only. Its
facts are fictional and exist solely to prove the RAG ingestion → retrieval
→ grounded-answer pipeline works end to end.

Founding and mission: LaraVisionX was founded to help engineering teams
adopt AI-assisted automation without vendor lock-in. Our mission is to
build agentic tooling that runs on infrastructure our customers already
control.

Products: LaraVisionX offers three demo product lines — Agent Studio (for
building custom AI agents), TestPilot (AI-assisted test generation for
Playwright and Tosca), and Insight Briefing (a daily technology
intelligence digest).

Support policy: Standard support response time for DEMO customers is one
business day. Enterprise support tier customers get a 4-hour response SLA.
These figures are demo placeholders, not real commitments.

Escalation policy: Any customer message mentioning "refund", "legal", or
"security incident" must be escalated to a human immediately and never
answered automatically.
"""


def seed_demo_users(db: Session) -> None:
    for email, password, role in DEMO_USERS:
        existing = db.query(UserORM).filter_by(email=email).first()
        if existing:
            continue
        db.add(UserORM(email=email, password_hash=hash_password(password), role=role.value))
    db.commit()


def seed_demo_knowledge(db: Session) -> None:
    existing = db.query(KnowledgeDocumentORM).filter_by(title=DEMO_KNOWLEDGE_TITLE).first()
    if existing:
        return

    admin = db.query(UserORM).filter_by(email="admin@laravisionx.com").first()
    from agents.knowledge import knowledge_agent
    from packages.config.llm_provider import get_llm_provider

    try:
        knowledge_agent.ingest_document(
            db,
            actor_id=admin.id if admin else "seed",
            title=DEMO_KNOWLEDGE_TITLE,
            source="seed_data",
            raw_text=DEMO_KNOWLEDGE_TEXT,
            access_role=Role.VIEWER,
            llm=get_llm_provider(),
        )
    except RuntimeError:
        # Ollama not reachable at startup — knowledge seeding is best-effort;
        # the app still starts, ingestion can be retried once the LLM is up.
        db.rollback()
