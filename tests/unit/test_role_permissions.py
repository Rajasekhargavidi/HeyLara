"""Unit tests for the orchestrator's role-permission gates.

No server, DB, or LLM needed — these exercise the pure permission-check
functions directly, per the spec's "agent tool permissions are tested" and
"approval bypass tests fail safely" quality gates.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.orchestrator import orchestrator  # noqa: E402
from packages.schemas.models import Role  # noqa: E402


class _FakeUser:
    def __init__(self, role: Role) -> None:
        self.role = role
        self.id = "test-user"
        self.email = "test@example.com"


@pytest.mark.parametrize("role", [Role.ADMIN, Role.MARKETING])
def test_social_write_allowed_for_admin_and_marketing(role):
    orchestrator._require_social_write(_FakeUser(role))  # must not raise


@pytest.mark.parametrize("role", [Role.SUPPORT, Role.VIEWER])
def test_social_write_denied_for_support_and_viewer(role):
    with pytest.raises(HTTPException) as exc_info:
        orchestrator._require_social_write(_FakeUser(role))
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("role", [Role.ADMIN, Role.SUPPORT])
def test_customer_write_allowed_for_admin_and_support(role):
    orchestrator._require_customer_write(_FakeUser(role))  # must not raise


@pytest.mark.parametrize("role", [Role.MARKETING, Role.VIEWER])
def test_customer_write_denied_for_marketing_and_viewer(role):
    with pytest.raises(HTTPException) as exc_info:
        orchestrator._require_customer_write(_FakeUser(role))
    assert exc_info.value.status_code == 403


def test_ceo_report_roles_are_admin_and_viewer_only():
    # Documents the intentional, narrower-than-spec-minimum choice: exec
    # visibility is ADMIN+VIEWER, not ADMIN+MARKETING+SUPPORT+VIEWER.
    assert orchestrator._CEO_REPORT_ROLES == {Role.ADMIN, Role.VIEWER}


def test_no_role_is_accidentally_granted_every_permission():
    """An approval-bypass regression would show up as some non-ADMIN role
    ending up in every write-role set. Guards against that class of bug."""
    write_role_sets = [
        orchestrator._SOCIAL_WRITE_ROLES,
        orchestrator._CUSTOMER_WRITE_ROLES,
    ]
    for role in (Role.MARKETING, Role.SUPPORT, Role.VIEWER):
        assert not all(role in s for s in write_role_sets), (
            f"{role} unexpectedly has every write permission — check for an approval bypass"
        )
