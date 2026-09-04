"""JARVIS API — Phase 2 (auth + persistence).

Adds local JWT/session auth and Postgres/SQLite-backed persistence on top
of Phase 1's chat -> Orchestrator -> Agent -> Tool Registry loop.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.auth import CurrentUser, create_access_token, get_current_user, verify_password  # noqa: E402
from apps.api.db import get_db, init_db  # noqa: E402
from apps.api import oauth_linkedin  # noqa: E402
from apps.api.models_db import (  # noqa: E402
    AuditEventORM,
    CustomerMessageORM,
    LeadORM,
    PostDraftORM,
    PublishedPostORM,
    TechnologyUpdateORM,
    UserORM,
)
from apps.api.seed import seed_demo_knowledge, seed_demo_users  # noqa: E402
from agents.analytics import analytics_agent  # noqa: E402
from agents.crm import crm_agent  # noqa: E402
from agents.customer import customer_agent  # noqa: E402
from agents.employee import employee_agent  # noqa: E402
from agents.knowledge import knowledge_agent  # noqa: E402
from agents.orchestrator import orchestrator  # noqa: E402
from agents.technology import technology_agent  # noqa: E402
from packages.config.llm_provider import get_llm_provider  # noqa: E402
from packages.config.settings import settings  # noqa: E402
from packages.schemas.models import Role  # noqa: E402
from tools.registry.bootstrap import bootstrap_tools  # noqa: E402
from tools.registry.registry import registry  # noqa: E402

_SOCIAL_WRITE_ROLES = (Role.ADMIN, Role.MARKETING)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jarvis.api")

bootstrap_tools()

app = FastAPI(title="LaraVisionX JARVIS API", version="0.2.0-phase2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = next(get_db())
    try:
        seed_demo_users(db)
        seed_demo_knowledge(db)
        customer_agent.seed_demo_conversations(db)
        employee_agent.seed_demo_employees(db)
    finally:
        db.close()

    def _audit_sink(entry: dict) -> None:
        db = next(get_db())
        try:
            db.add(AuditEventORM(
                actor=entry["actor"],
                tool=entry["tool"],
                args=entry["args"],
                ok=entry["ok"],
                error=entry.get("error"),
                duration_ms=entry.get("duration_ms", 0),
            ))
            db.commit()
        finally:
            db.close()

    registry.audit_sink = _audit_sink


class ChatRequest(BaseModel):
    message: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "phase": 2,
        "jarvis_mode": settings.jarvis_mode,
        "llm_provider": settings.llm_provider,
    }


@app.post("/api/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(UserORM).filter_by(email=req.email).first()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    token = create_access_token(user)
    return LoginResponse(access_token=token, role=user.role, email=user.email)


@app.get("/api/auth/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role.value}


@app.post("/api/chat")
def chat(req: ChatRequest, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return orchestrator.handle_command(db, user, req.message)


@app.get("/api/audit-log")
def audit_log(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    if user.role not in (Role.ADMIN, Role.VIEWER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Audit log is restricted to ADMIN/VIEWER")
    rows = db.query(AuditEventORM).order_by(AuditEventORM.created_at.desc()).limit(200).all()
    return [
        {
            "actor": r.actor,
            "tool": r.tool,
            "args": r.args,
            "ok": r.ok,
            "error": r.error,
            "duration_ms": r.duration_ms,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@app.post("/api/knowledge/ingest")
def ingest_knowledge(
    file: UploadFile = File(...),
    title: str = Form(...),
    access_role: str = Form("VIEWER"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role not in _SOCIAL_WRITE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only ADMIN/MARKETING can ingest company knowledge")

    suffix = Path(file.filename or "").suffix or ".txt"
    raw_bytes = file.file.read()
    try:
        role = Role(access_role.upper())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid access_role '{access_role}'")

    try:
        document = knowledge_agent.ingest_document(
            db,
            actor_id=user.id,
            title=title,
            source=file.filename or "upload",
            file_path=f"upload{suffix}",
            raw_bytes=raw_bytes,
            access_role=role,
            llm=get_llm_provider(),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {"id": document.id, "title": document.title, "chunks": document.chunk_count}


@app.get("/api/knowledge/documents")
def list_knowledge_documents(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    docs = knowledge_agent.list_documents(db, user.role)
    return [
        {
            "id": d.id,
            "title": d.title,
            "source": d.source,
            "access_role": d.access_role,
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]


@app.get("/api/technology/briefing")
def technology_briefing(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    updates = technology_agent.get_recent_updates(db)
    return [
        {
            "title": u.title,
            "url": u.url,
            "source": u.source,
            "topic": u.topic,
            "what_changed": u.what_changed,
            "why_care": u.why_care,
            "recommended_action": u.recommended_action,
            "confidence": u.confidence,
            "rank": u.rank,
            "discovered_at": u.discovered_at.isoformat(),
        }
        for u in updates
    ]


@app.get("/api/customer/messages")
def customer_messages(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    messages = customer_agent.list_messages(db)
    return [
        {
            "id": m.id,
            "conversation_id": m.conversation_id,
            "sender": m.sender,
            "content": m.content,
            "classification": m.classification,
            "status": m.status,
            "draft_reply": m.draft_reply,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


@app.get("/api/leads")
def leads(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": l.id,
            "conversation_id": l.conversation_id,
            "name": l.name,
            "contact": l.contact,
            "notes": l.notes,
            "created_at": l.created_at.isoformat(),
        }
        for l in crm_agent.list_leads(db)
    ]


@app.get("/api/ceo/overview")
def ceo_overview(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role not in (Role.ADMIN, Role.VIEWER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CEO Overview is restricted to ADMIN/VIEWER")
    # Fast tile counts only — no LLM call, unlike the full "generate the CEO
    # report" chat action which also synthesizes recommendations.
    metrics = analytics_agent.get_metrics_summary(db, "weekly")
    return {
        "technology_updates_needing_attention": analytics_agent.count(db, TechnologyUpdateORM, rank="HIGH"),
        "posts_waiting_for_approval": analytics_agent.count(db, PostDraftORM, status="WAITING_APPROVAL"),
        "published_posts_total": analytics_agent.count(db, PublishedPostORM),
        "new_leads_total": analytics_agent.count(db, LeadORM),
        "customer_conversations_needing_attention": (
            db.query(CustomerMessageORM).filter(CustomerMessageORM.status.in_(["NEW", "ESCALATED"])).count()
        ),
        "agent_failures_total": analytics_agent.count(db, AuditEventORM, ok=False),
        "social_metrics": metrics,
        "top_performing_posts": analytics_agent.identify_top_performing(db, limit=3),
    }


@app.get("/api/employees")
def list_employees(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {"id": e.id, "name": e.name, "email": e.email, "teams_user_id": e.teams_user_id, "whatsapp_number": e.whatsapp_number}
        for e in employee_agent.list_employees(db)
    ]


@app.get("/api/employee-tasks")
def list_employee_tasks(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {
            "id": t.id,
            "employee_id": t.employee_id,
            "description": t.description,
            "channel": t.channel,
            "status": t.status,
            "latest_update": t.latest_update,
            "is_demo_data": t.is_demo_data,
            "updated_at": t.updated_at.isoformat(),
        }
        for t in employee_agent.list_tasks(db)
    ]


@app.get("/api/webhooks/whatsapp")
def whatsapp_webhook_verify(request: Request) -> PlainTextResponse:
    # Meta's webhook verification handshake — see
    # https://developers.facebook.com/docs/graph-api/webhooks/getting-started
    params = request.query_params
    if params.get("hub.verify_token") == settings.whatsapp_webhook_verify_token and params.get("hub.challenge"):
        return PlainTextResponse(params["hub.challenge"])
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid verify token")


@app.post("/api/webhooks/whatsapp")
def whatsapp_webhook_receive(payload: dict, db: Session = Depends(get_db)) -> dict:
    from tools.employee.whatsapp_provider import store_inbound_webhook_message

    store_inbound_webhook_message(db, payload)
    return {"received": True}


@app.get("/api/oauth/linkedin/start")
def linkedin_oauth_start(user: CurrentUser = Depends(get_current_user)) -> dict:
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only ADMIN can start the LinkedIn OAuth flow")
    if not settings.linkedin_client_id or not settings.linkedin_client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET are not set in .env",
        )
    return {"authorization_url": oauth_linkedin.create_authorization_url()}


@app.get("/api/oauth/linkedin/callback")
def linkedin_oauth_callback(code: str = "", state: str = "", error: str = "", error_description: str = "") -> PlainTextResponse:
    # This endpoint is hit by LinkedIn's own redirect, not by a logged-in
    # JARVIS user — no Authorization header is available here. CSRF
    # protection instead comes from the one-time `state` value minted by
    # /api/oauth/linkedin/start and validated below.
    if error:
        return PlainTextResponse(f"LinkedIn authorization was not granted: {error} — {error_description}", status_code=400)
    if not code or not oauth_linkedin.validate_state(state):
        return PlainTextResponse("Missing or invalid/expired state — start the flow again from /api/oauth/linkedin/start.", status_code=400)

    try:
        token_data = oauth_linkedin.exchange_code_for_token(code)
    except RuntimeError as exc:
        return PlainTextResponse(f"Token exchange failed: {exc}", status_code=400)

    access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in", "?")
    orgs = oauth_linkedin.list_admin_organizations(access_token) if access_token else []

    org_lines = "\n".join(f"  - {o.get('name', '(unknown name)')}  ->  LINKEDIN_ORG_URN={o.get('org_urn', '')}" for o in orgs) or "  (none found — check that the token has organization admin access)"

    body = (
        "LinkedIn authorization succeeded.\n\n"
        f"Access token (expires in {expires_in} seconds):\n{access_token}\n\n"
        "Organizations this token can administer:\n"
        f"{org_lines}\n\n"
        "Next step: copy the LINKEDIN_ORG_URN line for LaraVisionX and the access token "
        "above into your .env as LINKEDIN_ACCESS_TOKEN and LINKEDIN_ORG_URN, then restart JARVIS.\n"
        "This token is only shown once here — copy it now."
    )
    return PlainTextResponse(body)


web_dir = REPO_ROOT / "apps" / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
