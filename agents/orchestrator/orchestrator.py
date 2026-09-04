"""JARVIS Orchestrator — Phase 4 (Ollama-driven planning).

Understands a request via the local LLM's tool-calling, delegates to a
specialist agent, and returns a structured response. Intent routing is no
longer keyword-based: the model chooses which tool (if any) to call from
an explicit, allow-listed schema — it can never invoke anything outside
this list, and every mutating tool is still role-checked before it reaches
the Tool Registry. If the model doesn't choose a tool, JARVIS answers
directly (e.g. small talk, general questions) without touching any agent.
"""
from __future__ import annotations

import json

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from agents.analytics import analytics_agent
from agents.content import content_agent
from agents.crm import crm_agent
from agents.customer import customer_agent
from agents.employee import employee_agent
from agents.knowledge import knowledge_agent
from agents.social import social_agent
from agents.technology import technology_agent
from apps.api.auth import CurrentUser
from apps.api.models_db import CustomerMessageORM, EmployeeTaskORM, LeadORM, PostDraftORM, PublishedPostORM
from packages.config.llm_provider import ToolCall, get_llm_provider
from packages.schemas.models import Platform, Role

# Roles allowed to create/approve/publish social content.
_SOCIAL_WRITE_ROLES = {Role.ADMIN, Role.MARKETING}
# Roles allowed to handle customer conversations and leads.
_CUSTOMER_WRITE_ROLES = {Role.ADMIN, Role.SUPPORT}
# Roles allowed to see the cross-domain CEO report (exec-level visibility).
_CEO_REPORT_ROLES = {Role.ADMIN, Role.VIEWER}
# Only ADMIN manages employee task assignment — not covered explicitly by
# the spec's role model, so this is a documented, conservative default.
_EMPLOYEE_WRITE_ROLES = {Role.ADMIN}

SYSTEM_PROMPT = (
    "You are JARVIS, the central AI operating assistant for LaraVisionX. "
    "Talk like a warm, capable friend and colleague, not a formal report generator — "
    "casual, direct, a little conversational. Address the user like you'd talk to "
    "someone you work closely with and like. Keep small talk and direct answers "
    "short and natural, not stiff or robotic. This tone applies to how you phrase "
    "things, never to the facts themselves — the accuracy rules below are absolute "
    "regardless of tone. "
    "Understand the goal, and call the right tool to accomplish it. "
    "Only call a tool when the user is asking for an action this system can "
    "actually perform (creating/approving/publishing social content, "
    "listing approvals, or reporting metrics). For greetings, general "
    "questions, or anything outside these tools, just answer directly in "
    "plain text — do not invent a tool call for it. "
    "Never invent company facts, pricing, metrics, customer information, "
    "or publication status. If you don't know something, say so. "
    "For any question about LaraVisionX itself — its policies, offerings, "
    "processes, or other company-specific facts — always call "
    "search_knowledge rather than answering from your own knowledge. "
    "For questions about external technology/AI/industry news, use "
    "get_technology_briefing. For inbound customer messages, use "
    "list_customer_messages / draft_customer_reply / send_customer_reply, "
    "and create_lead to capture a sales/partnership lead. Never invent "
    "pricing, discounts, guarantees, or policies in a customer reply — "
    "draft_customer_reply already grounds its answer in company knowledge. "
    "For a CEO/executive summary across the whole business, use generate_report. "
    "To ping an employee with a task or check on one, use assign_employee_task, "
    "request_employee_status_update, or list_employee_tasks."
)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_campaign",
            "description": "Draft new social media post(s) about a topic. Requires approval before publishing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "What the post should be about"},
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string", "enum": [p.value for p in Platform]},
                        "description": "Target platforms, defaults to [LINKEDIN] if unspecified",
                    },
                    "variants": {
                        "type": "integer",
                        "description": "How many distinct draft variants to generate per platform (1-3, default 1). Use >1 when the user asks for options/variants to choose from.",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pending_approvals",
            "description": "List post drafts currently waiting for approval.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_and_publish",
            "description": "Approve a pending draft by its id and publish it via the (mock) social provider.",
            "parameters": {
                "type": "object",
                "properties": {"draft_id": {"type": "string", "description": "The draft's UUID"}},
                "required": ["draft_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_metrics",
            "description": "Report DEMO DATA performance metrics for the most recently published post.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_content_concepts",
            "description": (
                "Generate creative concepts for a topic: a short-form video concept, a carousel "
                "post concept, hashtags, and a call to action. Does not create/publish a post draft "
                "— purely ideation, for the user to review. Use when asked for video/carousel/creative ideas."
            ),
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_technology_briefing",
            "description": (
                "Get the latest technology/AI/Playwright/Tosca/AEM/DevOps intelligence briefing. "
                "Use refresh=true when the user explicitly asks to research/find/check for new updates "
                "(e.g. 'today's briefing', 'find the latest AI updates'); use refresh=false to just show "
                "what's already been found."
            ),
            "parameters": {
                "type": "object",
                "properties": {"refresh": {"type": "boolean", "description": "Search the web for new items first"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Answer a question about LaraVisionX itself using the company knowledge base "
                "(ingested documents), with citations. Use this for any company-specific question."
            ),
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_customer_messages",
            "description": "List inbound customer messages and their status (NEW/DRAFTED/ESCALATED/RESOLVED).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_customer_reply",
            "description": (
                "Classify a customer message and draft a reply. Low-risk FAQs are answered grounded in "
                "company knowledge. Complaints/legal/refund/security messages are escalated for human "
                "review instead of auto-answered."
            ),
            "parameters": {
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_customer_reply",
            "description": "Send a drafted customer reply (requires a prior draft_customer_reply call).",
            "parameters": {
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_lead",
            "description": "Capture a sales/partnership lead. Only capture information the customer actually gave — never invent details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string", "description": "The customer conversation this lead came from, if any"},
                    "name": {"type": "string"},
                    "contact": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_employee_task",
            "description": "Assign a task to an employee via Teams or WhatsApp (falls back to a simulated demo channel if not configured for real).",
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_name": {"type": "string", "description": "The employee's name (partial match ok)"},
                    "description": {"type": "string", "description": "What the task is"},
                    "channel": {"type": "string", "enum": ["teams", "whatsapp"], "description": "Defaults to whatsapp"},
                },
                "required": ["employee_name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_employee_status_update",
            "description": "Ping an employee for a status update on a task: what's done, what's pending, when it'll complete.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_employee_tasks",
            "description": "List all assigned employee tasks and their latest status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": (
                "Generate the CEO/executive report: technology updates needing attention, "
                "posts awaiting approval, published posts, social reach/engagement vs previous "
                "period, top-performing content, new leads, customer conversations needing "
                "attention, agent failures, and recommendations. Use for 'weekly report', "
                "'CEO report', 'give me an overview' type requests."
            ),
            "parameters": {
                "type": "object",
                "properties": {"period": {"type": "string", "enum": ["today", "weekly"]}},
                "required": [],
            },
        },
    },
]


def _structured(objective: str, plan: list[str], actions: list[str], results: dict,
                 approvals_needed: list[str], risks: list[str], next_step: str) -> dict:
    return {
        "objective": objective,
        "plan": plan,
        "actions": actions,
        "results": results,
        "approvals_needed": approvals_needed,
        "risks_limitations": risks,
        "recommended_next_step": next_step,
    }


def _draft_to_dict(d: PostDraftORM) -> dict:
    return {
        "id": d.id,
        "platform": d.platform,
        "content": d.content,
        "hashtags": d.hashtags,
        "status": d.status,
        "created_at": d.created_at.isoformat(),
    }


def _published_to_dict(p: PublishedPostORM) -> dict:
    return {
        "id": p.id,
        "draft_id": p.draft_id,
        "platform": p.platform,
        "provider_post_id": p.provider_post_id,
        "published_at": p.published_at.isoformat(),
        "is_demo_data": p.is_demo_data,
    }


def _require_social_write(user: CurrentUser) -> None:
    if user.role not in _SOCIAL_WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.value}' cannot create or publish social content",
        )


def _coerce_platform_list(raw) -> list[Platform] | None:
    """Small local models sometimes return array-typed tool arguments as a
    stringified list (e.g. "['LINKEDIN', 'INSTAGRAM']") instead of a real
    JSON array. Normalize both shapes rather than trusting the schema."""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw.replace("'", '"'))
            raw = parsed if isinstance(parsed, list) else [raw]
        except json.JSONDecodeError:
            raw = [p.strip(" '\"[]") for p in raw.strip("[]").split(",") if p.strip(" '\"[]")]
    platforms = []
    for p in raw:
        try:
            platforms.append(Platform(str(p).strip(" '\"")))
        except ValueError:
            continue
    return platforms or None


def _run_create_campaign(db: Session, user: CurrentUser, args: dict) -> dict:
    _require_social_write(user)
    topic = args.get("topic", "").strip() or "our latest work"
    raw_platforms = args.get("platforms") or ([args["platform"]] if args.get("platform") else None)
    platforms = _coerce_platform_list(raw_platforms) or [Platform.LINKEDIN]
    variants = int(args.get("variants", 1) or 1)
    llm = get_llm_provider()
    drafts = social_agent.create_campaign_drafts(db, user.id, topic, llm, platforms=platforms, variants=variants)
    return _structured(
        objective=f"Create social content for: {topic}",
        plan=[
            f"Generate draft(s) via Content Agent/LLM across {len(platforms)} platform(s), {variants} variant(s) each",
            "Submit for approval",
            "Wait for CEO/marketing approval",
        ],
        actions=[f"create_post_draft x{len(drafts)}"],
        results={"drafts": [_draft_to_dict(d) for d in drafts]},
        approvals_needed=[f"Approve draft {d.id}" for d in drafts],
        risks=["Draft content is LLM-generated and unverified — review before approving"],
        next_step="Review drafts in Approval Queue and approve one to publish (DEMO/mock publish).",
    )


def _run_generate_content_concepts(db: Session, user: CurrentUser, args: dict) -> dict:
    _require_social_write(user)
    topic = args.get("topic", "").strip() or "our latest work"
    llm = get_llm_provider()
    concepts = content_agent.generate_creative_concepts(llm, topic)
    return _structured(
        objective=f"Generate creative concepts for: {topic}",
        plan=["Generate short-form video concept, carousel concept, hashtags, and CTA via Content Agent/LLM"],
        actions=["generate_content_concepts"],
        results={
            "short_form_video_concept": concepts.short_form_video_concept,
            "carousel_concept": concepts.carousel_concept,
            "hashtags": concepts.hashtags,
            "cta": concepts.cta,
        },
        approvals_needed=[],
        risks=["These are ideation concepts, not published content — no approval needed to view them"],
        next_step="Ask JARVIS to turn one of these into an actual post draft if you want to publish it.",
    )


def _run_list_pending_approvals(db: Session, user: CurrentUser, args: dict) -> dict:
    pending = social_agent.list_pending_approvals(db)
    return _structured(
        objective="List actions waiting for approval",
        plan=["Query approval queue"],
        actions=["list_pending_approvals"],
        results={"pending": [_draft_to_dict(d) for d in pending]},
        approvals_needed=[],
        risks=[],
        next_step="Say 'approve <draft_id>' to publish one.",
    )


def _run_approve_and_publish(db: Session, user: CurrentUser, args: dict) -> dict:
    _require_social_write(user)
    draft_id = args.get("draft_id", "").strip()
    if not draft_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="draft_id is required")
    published = social_agent.approve_and_publish(db, draft_id, actor_id=user.id, actor_label=user.email)
    return _structured(
        objective=f"Approve and publish draft {draft_id}",
        plan=["Publish via mock social provider", "Record published post"],
        actions=["publish_social_post"],
        results={"published_post": _published_to_dict(published)},
        approvals_needed=[],
        risks=["This is a MOCK publish — no real social account was touched"],
        next_step="Ask JARVIS to 'show post metrics' to see DEMO DATA analytics.",
    )


def _run_report_metrics(db: Session, user: CurrentUser, args: dict) -> dict:
    published = social_agent.list_published_posts(db)
    if not published:
        return _structured(
            objective="Report post performance",
            plan=["Check published posts"],
            actions=[],
            results={"published_posts": []},
            approvals_needed=[],
            risks=["No posts have been published yet"],
            next_step="Publish a post first, then ask for metrics again.",
        )
    latest = published[0]
    metrics = social_agent.report_metrics(db, latest.id)
    return _structured(
        objective="Report post performance (DEMO DATA)",
        plan=["Fetch metrics for latest published post"],
        actions=["fetch_post_metrics"],
        results={
            "post": _published_to_dict(latest),
            "metrics": {
                "reach": metrics.reach,
                "impressions": metrics.impressions,
                "likes": metrics.likes,
                "comments": metrics.comments,
                "shares": metrics.shares,
                "saves": metrics.saves,
                "clicks": metrics.clicks,
                "is_demo_data": metrics.is_demo_data,
                "captured_at": metrics.captured_at.isoformat(),
            },
        },
        approvals_needed=[],
        risks=["All metrics are DEMO DATA — no real platform was queried"],
        next_step="Connect a real SocialProvider adapter to replace mock metrics.",
    )


def _tech_update_to_dict(u) -> dict:
    return {
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


def _run_get_technology_briefing(db: Session, user: CurrentUser, args: dict) -> dict:
    llm = get_llm_provider()
    plan = ["Query stored technology updates"]
    if args.get("refresh"):
        plan = ["Search the web for new items per topic", "Deduplicate against stored updates",
                "Analyze and rank each new item", "Store and return the briefing"]
        try:
            technology_agent.run_briefing(db, user.id, llm)
        except RuntimeError as exc:
            return _structured(
                objective="Refresh technology briefing",
                plan=plan,
                actions=["search_web_or_sources"],
                results={},
                approvals_needed=[],
                risks=[f"Web search failed: {exc}"],
                next_step="Try again later, or ask for the briefing without refreshing.",
            )

    updates = technology_agent.get_recent_updates(db)
    return _structured(
        objective="Today's technology intelligence briefing",
        plan=plan,
        actions=["get_technology_briefing"],
        results={"updates": [_tech_update_to_dict(u) for u in updates]},
        approvals_needed=[],
        risks=["Item summaries are LLM-generated from search snippets — verify anything important before acting on it"]
        if updates else ["No technology updates stored yet"],
        next_step="Ask JARVIS to 'research today's AI and Playwright updates' to refresh with a live web search."
        if not args.get("refresh") else "Review HIGH-rank items first.",
    )


def _run_search_knowledge(db: Session, user: CurrentUser, args: dict) -> dict:
    question = args.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="question is required")
    llm = get_llm_provider()
    result = knowledge_agent.answer_from_knowledge(db, llm, user.role, question)
    grounded = bool(result["sources"])
    return _structured(
        objective=f"Answer from company knowledge: {question}",
        plan=["Embed question", "Retrieve top matching chunks (permission-filtered)", "Answer grounded in retrieved context"],
        actions=["search_knowledge"],
        results={"answer": result["answer"], "sources": result["sources"]},
        approvals_needed=[],
        risks=[] if grounded else ["No matching company knowledge was found for this question"],
        next_step="Ingest more documents via /api/knowledge/ingest if this area of company knowledge is missing.",
    )


def _require_customer_write(user: CurrentUser) -> None:
    if user.role not in _CUSTOMER_WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.value}' cannot handle customer conversations or leads",
        )


def _message_to_dict(m: CustomerMessageORM) -> dict:
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "sender": m.sender,
        "content": m.content,
        "classification": m.classification,
        "status": m.status,
        "draft_reply": m.draft_reply,
        "created_at": m.created_at.isoformat(),
    }


def _lead_to_dict(l: LeadORM) -> dict:
    return {
        "id": l.id,
        "conversation_id": l.conversation_id,
        "name": l.name,
        "contact": l.contact,
        "notes": l.notes,
        "created_at": l.created_at.isoformat(),
    }


def _run_list_customer_messages(db: Session, user: CurrentUser, args: dict) -> dict:
    messages = customer_agent.list_messages(db)
    return _structured(
        objective="List inbound customer messages",
        plan=["Query customer inbox"],
        actions=["list_customer_messages"],
        results={"messages": [_message_to_dict(m) for m in messages]},
        approvals_needed=[],
        risks=["Messages are DEMO DATA sample conversations, not real social accounts"],
        next_step="Ask JARVIS to 'draft a reply to message <id>'.",
    )


def _run_draft_customer_reply(db: Session, user: CurrentUser, args: dict) -> dict:
    _require_customer_write(user)
    message_id = args.get("message_id", "").strip()
    if not message_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="message_id is required")
    llm = get_llm_provider()
    message = customer_agent.draft_reply(db, llm, user.role, message_id)
    escalated = message.status == "ESCALATED"
    return _structured(
        objective=f"Draft a reply to customer message {message_id}",
        plan=["Classify message", "Escalate if sensitive, else answer grounded in company knowledge"],
        actions=["draft_customer_reply"],
        results={"message": _message_to_dict(message)},
        approvals_needed=[f"Human review required before sending message {message_id}"] if escalated else [],
        risks=["Escalated: this needs a human response, do not auto-send"] if escalated else
              ["Draft is grounded in company knowledge but should be reviewed before sending"],
        next_step="A human must handle this directly (see Customer Inbox)." if escalated else
                   f"Ask JARVIS to 'send reply to message {message_id}' to send it.",
    )


def _run_send_customer_reply(db: Session, user: CurrentUser, args: dict) -> dict:
    _require_customer_write(user)
    message_id = args.get("message_id", "").strip()
    if not message_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="message_id is required")
    message = customer_agent.send_reply(db, message_id, actor_label=user.email)
    return _structured(
        objective=f"Send reply to customer message {message_id}",
        plan=["Send drafted reply", "Mark message resolved"],
        actions=["send_customer_reply"],
        results={"message": _message_to_dict(message)},
        approvals_needed=[],
        risks=["This is a MOCK send — no real customer account was contacted"],
        next_step="Check the Customer Inbox for the resolved conversation.",
    )


def _run_create_lead(db: Session, user: CurrentUser, args: dict) -> dict:
    _require_customer_write(user)
    lead = crm_agent.create_lead(
        db, user.id,
        conversation_id=args.get("conversation_id"),
        name=args.get("name"),
        contact=args.get("contact"),
        notes=args.get("notes"),
    )
    return _structured(
        objective="Capture a new lead",
        plan=["Store only the information provided — nothing invented"],
        actions=["create_lead"],
        results={"lead": _lead_to_dict(lead)},
        approvals_needed=[],
        risks=[],
        next_step="View it in the Leads dashboard tab.",
    )


def _task_to_dict(t: EmployeeTaskORM) -> dict:
    return {
        "id": t.id,
        "employee_id": t.employee_id,
        "description": t.description,
        "channel": t.channel,
        "status": t.status,
        "latest_update": t.latest_update,
        "is_demo_data": t.is_demo_data,
        "updated_at": t.updated_at.isoformat(),
    }


def _require_employee_write(user: CurrentUser) -> None:
    if user.role not in _EMPLOYEE_WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.value}' cannot assign or manage employee tasks",
        )


def _run_assign_employee_task(db: Session, user: CurrentUser, args: dict) -> dict:
    _require_employee_write(user)
    employee_name = args.get("employee_name", "").strip()
    description = args.get("description", "").strip()
    channel = args.get("channel", "whatsapp")
    if not employee_name or not description:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="employee_name and description are required")

    employee = employee_agent.find_employee_by_name(db, employee_name)
    if employee is None:
        return _structured(
            objective=f"Assign a task to {employee_name}",
            plan=["Look up employee by name"],
            actions=[],
            results={},
            approvals_needed=[],
            risks=[f"No employee found matching '{employee_name}'"],
            next_step="Check the Employee Tasks tab for the list of known employees.",
        )

    task = employee_agent.assign_task(db, user.id, employee.id, description, channel)
    return _structured(
        objective=f"Assign task to {employee.name}",
        plan=[f"Send task via {channel}", "Record task as ASSIGNED"],
        actions=["assign_employee_task"],
        results={"task": _task_to_dict(task)},
        approvals_needed=[],
        risks=["This is a simulated/demo channel send"] if task.is_demo_data else [],
        next_step=f"Ask JARVIS to 'request a status update on task {task.id}' later.",
    )


def _run_request_employee_status_update(db: Session, user: CurrentUser, args: dict) -> dict:
    _require_employee_write(user)
    task_id = args.get("task_id", "").strip()
    if not task_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="task_id is required")
    task = employee_agent.request_status_update(db, task_id)
    return _structured(
        objective=f"Request a status update for task {task_id}",
        plan=["Ping employee for status", "Record their reply if available immediately (demo mode)"],
        actions=["request_employee_status_update"],
        results={"task": _task_to_dict(task)},
        approvals_needed=[],
        risks=["Demo channel reply is simulated" if task.is_demo_data else
               ["Real channel reply may arrive later via webhook — check back"]],
        next_step="Check the Employee Tasks tab for the latest update.",
    )


def _run_list_employee_tasks(db: Session, user: CurrentUser, args: dict) -> dict:
    tasks = employee_agent.list_tasks(db)
    return _structured(
        objective="List employee tasks",
        plan=["Query all assigned tasks"],
        actions=["list_employee_tasks"],
        results={"tasks": [_task_to_dict(t) for t in tasks]},
        approvals_needed=[],
        risks=[],
        next_step="Ask JARVIS to assign a new task or request a status update on an existing one.",
    )


def _run_generate_report(db: Session, user: CurrentUser, args: dict) -> dict:
    if user.role not in _CEO_REPORT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.value}' cannot view the CEO/executive report",
        )
    period = args.get("period", "weekly")
    llm = get_llm_provider()
    report = analytics_agent.build_ceo_report(db, llm, period)
    return _structured(
        objective=f"Generate the {period} CEO report",
        plan=[
            "Query real counts across technology, social, customer, and CRM data",
            "Compute social metrics vs the previous period (where enough data exists)",
            "Identify top-performing content without claiming unproven causation",
            "Synthesize recommendations strictly from the confirmed numbers above",
        ],
        actions=["generate_report"],
        results=report,
        approvals_needed=[],
        risks=["Recommendations are LLM-synthesized from real counts, but should be sanity-checked before acting on them"],
        next_step="Review the Approval Queue, Technology Briefing, and Customer Inbox for anything flagged above.",
    )


_DISPATCH = {
    "create_campaign": _run_create_campaign,
    "generate_report": _run_generate_report,
    "assign_employee_task": _run_assign_employee_task,
    "request_employee_status_update": _run_request_employee_status_update,
    "list_employee_tasks": _run_list_employee_tasks,
    "list_customer_messages": _run_list_customer_messages,
    "draft_customer_reply": _run_draft_customer_reply,
    "send_customer_reply": _run_send_customer_reply,
    "create_lead": _run_create_lead,
    "generate_content_concepts": _run_generate_content_concepts,
    "list_pending_approvals": _run_list_pending_approvals,
    "approve_and_publish": _run_approve_and_publish,
    "report_metrics": _run_report_metrics,
    "search_knowledge": _run_search_knowledge,
    "get_technology_briefing": _run_get_technology_briefing,
}


def _fallback_answer(text: str) -> dict:
    llm = get_llm_provider()
    try:
        answer = llm.generate(text, system=SYSTEM_PROMPT).strip()
    except RuntimeError as exc:
        answer = (
            "I can't reach the local LLM right now, so I can only help with a fixed set of "
            "actions: creating a campaign, listing pending approvals, approving/publishing a "
            f"draft, or reporting metrics. ({exc})"
        )
    return _structured(
        objective=text,
        plan=["No agent action needed — answered directly"],
        actions=[],
        results={"answer": answer},
        approvals_needed=[],
        risks=["Direct LLM answers are not grounded in company knowledge (RAG lands in Phase 5)"],
        next_step="Ask JARVIS to create a campaign, list approvals, approve a draft, or show metrics.",
    )


def handle_command(db: Session, user: CurrentUser, text: str) -> dict:
    llm = get_llm_provider()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    try:
        result = llm.generate_with_tools(messages, _TOOLS)
    except RuntimeError:
        return _fallback_answer(text)

    if not result.tool_calls:
        if result.text.strip():
            return _structured(
                objective=text,
                plan=["No agent action needed — answered directly"],
                actions=[],
                results={"answer": result.text.strip()},
                approvals_needed=[],
                risks=["Direct LLM answers are not grounded in company knowledge (RAG lands in Phase 5)"],
                next_step="Ask JARVIS to create a campaign, list approvals, approve a draft, or show metrics.",
            )
        return _fallback_answer(text)

    call: ToolCall = result.tool_calls[0]
    handler = _DISPATCH.get(call.name)
    if handler is None:
        return _structured(
            objective=text,
            plan=[f"Model requested unknown tool '{call.name}'"],
            actions=[],
            results={},
            approvals_needed=[],
            risks=[f"'{call.name}' is not on the Tool Registry allow-list"],
            next_step="Try: 'Create a LinkedIn campaign about <topic>', 'show pending approvals', "
                      "'approve <draft_id>', or 'show post metrics'.",
        )
    return handler(db, user, call.arguments)
