"""Shared fixtures for the Playwright E2E suite.

Assumes the JARVIS API is already running at BASE_URL (see README: `uvicorn
apps.api.main:app --port 8000`). Tests do not start the server themselves —
Phase 11 keeps this simple; wiring pytest to spin up/tear down the server
automatically is a natural follow-up once CI needs it.
"""
from __future__ import annotations

import os

import pytest
import requests

BASE_URL = os.environ.get("JARVIS_E2E_BASE_URL", "http://127.0.0.1:8000")

DEMO_USERS = {
    "ADMIN": ("admin@laravisionx.com", "admin123"),
    "MARKETING": ("marketing@laravisionx.com", "marketing123"),
    "SUPPORT": ("support@laravisionx.com", "support123"),
    "VIEWER": ("viewer@laravisionx.com", "viewer123"),
}


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session", autouse=True)
def _require_server(base_url):
    try:
        resp = requests.get(f"{base_url}/api/health", timeout=5)
        resp.raise_for_status()
    except requests.RequestException as exc:
        pytest.skip(f"JARVIS API is not running at {base_url} — start it before running E2E tests ({exc})")


def login_token(base_url: str, role: str) -> str:
    email, password = DEMO_USERS[role]
    resp = requests.post(f"{base_url}/api/auth/login", json={"email": email, "password": password}, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.fixture
def logged_in_page(page, base_url):
    """Returns a function that logs the Playwright page in as a given role
    by seeding localStorage directly (fast, deterministic) rather than
    driving the login form for every test — login-form UX itself is
    covered separately in test_login_flow."""

    def _login_as(role: str):
        token = login_token(base_url, role)
        email, _ = DEMO_USERS[role]
        page.goto(f"{base_url}/login.html")
        page.evaluate(
            """([token, role, email]) => {
                localStorage.setItem('jarvis_token', token);
                localStorage.setItem('jarvis_role', role);
                localStorage.setItem('jarvis_email', email);
            }""",
            [token, role, email],
        )
        page.goto(f"{base_url}/dashboard.html")
        return token

    return _login_as
