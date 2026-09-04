"""Lead/CRM Agent — Phase 9.

Captures only necessary lead information, per the CUSTOMER AGENT PROMPT's
"capture only necessary lead information" and "never ask for passwords,
OTPs, card PINs or unnecessary sensitive information."
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.models_db import LeadORM
from tools.registry.registry import registry

AGENT_NAME = "crm_agent"


def create_lead(
    db: Session,
    actor_id: str,
    conversation_id: str | None = None,
    name: str | None = None,
    contact: str | None = None,
    notes: str | None = None,
) -> LeadORM:
    registry.call("create_lead", actor=AGENT_NAME, conversation_id=conversation_id or "")

    lead = LeadORM(
        conversation_id=conversation_id,
        name=name,
        contact=contact,
        notes=notes,
        created_by=actor_id,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def list_leads(db: Session) -> list[LeadORM]:
    return db.query(LeadORM).order_by(LeadORM.created_at.desc()).all()
