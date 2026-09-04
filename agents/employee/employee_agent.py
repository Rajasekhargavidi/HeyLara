"""Employee / Task Coordinator Agent — Phase 12.

Pings employees via Teams or WhatsApp with a task, and captures their
status updates back — closing the loop the user asked for originally:
"call or ping employees ... and update them with tasks and also get the
updates from employees and finally share the status: what was done, what
is pending, when it's going to complete, what is planned ASAP."

Falls back to the mock channel automatically when real credentials aren't
configured (see tools/employee/factory.py) — every call still works
end-to-end in demo mode, just clearly labeled DEMO DATA.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.models_db import EmployeeORM, EmployeeTaskORM
from tools.employee.factory import get_employee_channel
from tools.registry.registry import registry

AGENT_NAME = "employee_agent"

DEMO_EMPLOYEES = [
    {"name": "Priya Sharma", "email": "priya.sharma@example.com", "whatsapp_number": "+10000000001"},
    {"name": "Daniel Osei", "email": "daniel.osei@example.com", "whatsapp_number": "+10000000002"},
]

_STATUS_KEYWORDS = {
    "DONE": ("done", "completed", "finished", "ready for review"),
    "BLOCKED": ("blocked", "waiting on", "dependency"),
    "IN_PROGRESS": ("started", "in progress", "working on", "on track"),
}


def seed_demo_employees(db: Session) -> None:
    if db.query(EmployeeORM).first():
        return
    for e in DEMO_EMPLOYEES:
        db.add(EmployeeORM(name=e["name"], email=e["email"], whatsapp_number=e["whatsapp_number"]))
    db.commit()


def list_employees(db: Session) -> list[EmployeeORM]:
    return db.query(EmployeeORM).order_by(EmployeeORM.name).all()


def find_employee_by_name(db: Session, name: str) -> EmployeeORM | None:
    return db.query(EmployeeORM).filter(EmployeeORM.name.ilike(f"%{name}%")).first()


def list_tasks(db: Session) -> list[EmployeeTaskORM]:
    return db.query(EmployeeTaskORM).order_by(EmployeeTaskORM.updated_at.desc()).all()


def _recipient_for(employee: EmployeeORM, channel: str) -> str:
    recipient = employee.teams_user_id if channel == "teams" else employee.whatsapp_number
    if not recipient:
        raise ValueError(f"Employee {employee.name} has no {channel} identifier on file")
    return recipient


def _infer_status(text: str, current_status: str) -> str:
    lowered = text.lower()
    for status, keywords in _STATUS_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return status
    return current_status


def assign_task(db: Session, actor_id: str, employee_id: str, description: str, channel: str = "whatsapp") -> EmployeeTaskORM:
    employee = db.get(EmployeeORM, employee_id)
    if employee is None:
        raise ValueError(f"No employee with id {employee_id}")

    registry.call("assign_employee_task", actor=AGENT_NAME, employee_id=employee_id, channel=channel)

    provider, is_real = get_employee_channel(channel)
    recipient = _recipient_for(employee, channel) if is_real else (employee.whatsapp_number or employee.email or employee.name)
    provider.send_message(recipient, f"New task from JARVIS: {description}")

    task = EmployeeTaskORM(
        employee_id=employee_id,
        description=description,
        channel=channel,
        status="ASSIGNED",
        is_demo_data=not is_real,
        created_by=actor_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def request_status_update(db: Session, task_id: str) -> EmployeeTaskORM:
    task = db.get(EmployeeTaskORM, task_id)
    if task is None:
        raise ValueError(f"No task with id {task_id}")
    employee = db.get(EmployeeORM, task.employee_id)

    registry.call("request_employee_status_update", actor=AGENT_NAME, employee_id=task.employee_id, channel=task.channel)

    provider, is_real = get_employee_channel(task.channel)
    recipient = _recipient_for(employee, task.channel) if is_real else (employee.whatsapp_number or employee.email or employee.name)
    provider.send_message(recipient, f"JARVIS status check: what's done, what's pending, and when will '{task.description}' complete?")

    # In demo mode there is no real async employee on the other end, so the
    # mock channel's canned reply stands in immediately. In live mode, real
    # replies arrive later via the platform's webhook (see
    # apps/api/main.py's /api/webhooks/whatsapp) and record_inbound_reply.
    if not is_real:
        replies = provider.get_recent_replies(recipient)
        if replies:
            reply_text = replies[0]["text"]
            task.latest_update = reply_text
            task.status = _infer_status(reply_text, task.status)
            db.commit()
            db.refresh(task)

    return task


def record_inbound_reply(db: Session, channel: str, sender: str, text: str) -> EmployeeTaskORM | None:
    """Called from a real webhook (WhatsApp/Teams) when an employee replies."""
    column = EmployeeORM.whatsapp_number if channel == "whatsapp" else EmployeeORM.teams_user_id
    employee = db.query(EmployeeORM).filter(column == sender).first()
    if employee is None:
        return None

    task = (
        db.query(EmployeeTaskORM)
        .filter(EmployeeTaskORM.employee_id == employee.id, EmployeeTaskORM.status != "DONE")
        .order_by(EmployeeTaskORM.updated_at.desc())
        .first()
    )
    if task is None:
        return None

    task.latest_update = text
    task.status = _infer_status(text, task.status)
    db.commit()
    db.refresh(task)
    return task
