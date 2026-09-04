"""Playwright E2E smoke tests — Phase 11.

Covers the core slice of the MVP ACCEPTANCE TEST from the master build
spec: login, dashboard tabs render real data, role-based access is
enforced in the UI (not just the API), and the end-to-end JARVIS chat loop
works. LLM-dependent flows are marked `slow` and kept to one test each,
since each round trip through the local model can take 10-90s — the rest
of the suite drives the UI against fast, deterministic API state so it
stays fast and reliable enough to run on every change.
"""
from __future__ import annotations

import uuid

import pytest
import requests
from playwright.sync_api import expect

from conftest import DEMO_USERS, login_token


def test_login_flow(page, base_url):
    page.goto(f"{base_url}/login.html")
    expect(page.locator("h1")).to_contain_text("JARVIS")

    page.fill("#email", "admin@laravisionx.com")
    page.fill("#password", "admin123")
    page.click("button:has-text('Sign in')")

    page.wait_for_url("**/dashboard.html")
    expect(page.locator("#whoami")).to_contain_text("admin@laravisionx.com")
    expect(page.locator("#whoami")).to_contain_text("ADMIN")


def test_login_rejects_bad_password(page, base_url):
    page.goto(f"{base_url}/login.html")
    page.fill("#email", "admin@laravisionx.com")
    page.fill("#password", "wrong-password")
    page.click("button:has-text('Sign in')")
    expect(page.locator("#error")).to_contain_text("Invalid email or password")
    # Must NOT navigate away from the login page on failure.
    expect(page).to_have_url(f"{base_url}/login.html")


@pytest.mark.parametrize("tab_label,heading", [
    ("CEO Overview", "CEO Overview"),
    ("Approval Queue", "Approval Queue"),
    ("Audit Log", "Audit Log"),
    ("Company Knowledge", "Company Knowledge"),
    ("Technology Briefing", "Technology Briefing"),
    ("Customer Inbox", "Customer Inbox"),
    ("Leads", "Leads"),
])
def test_dashboard_tabs_render(logged_in_page, page, tab_label, heading):
    logged_in_page("ADMIN")
    page.click(f".item:has-text('{tab_label}')")
    expect(page.locator("h2:visible")).to_have_text(heading)


def test_approval_queue_shows_a_pending_draft(logged_in_page, page, base_url):
    # Seed a draft directly via the API (fast, no LLM) so the UI test is
    # deterministic and doesn't depend on generation timing.
    token = login_token(base_url, "MARKETING")
    unique_topic = f"e2e test topic {uuid.uuid4().hex[:8]}"

    # There is no non-LLM way to create a post draft (content generation
    # always goes through the Content Agent), so this test accepts the one
    # real LLM round trip rather than mocking it out — this is the
    # "create a draft" step from the MVP acceptance test. The LLM rewrites
    # the topic into original prose rather than echoing it verbatim, so we
    # assert against the actual generated content the API returned, not
    # against unique_topic itself.
    chat_resp = requests.post(
        f"{base_url}/api/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": f"create a campaign about {unique_topic} for LinkedIn"},
        timeout=120,
    )
    chat_resp.raise_for_status()
    generated_content = chat_resp.json()["results"]["drafts"][0]["content"]
    needle = generated_content[:30]

    logged_in_page("ADMIN")
    page.click(".item:has-text('Approval Queue')")
    expect(page.locator("table#approvalsTable")).to_contain_text(needle, timeout=15000)


def test_customer_inbox_shows_seeded_demo_messages(logged_in_page, page):
    logged_in_page("SUPPORT")
    page.click(".item:has-text('Customer Inbox')")
    # Seeded on first startup — see tools/mock/customer_mock.py.
    expect(page.locator("#customerList")).to_contain_text("refund", timeout=10000)


def test_viewer_role_is_blocked_from_creating_content(logged_in_page, page):
    logged_in_page("VIEWER")
    # An unambiguous topic — a vague one ("about anything") lets a smarter
    # model correctly ask a clarifying question instead of calling the tool
    # at all, which would never reach the role check this test is for.
    page.fill("#input", "create a LinkedIn campaign about cloud security")
    page.click("button:has-text('Send')")
    # The API returns a 403 whose body still renders in the chat log —
    # the UI must surface the denial, not fail silently.
    # Generous timeout: this is often the first LLM call after a fresh
    # server start, and cold model load can take longer than a typical
    # warm round trip.
    expect(page.locator("#log")).to_contain_text("cannot create or publish", timeout=45000)


@pytest.mark.slow
def test_end_to_end_chat_answers_a_general_question(logged_in_page, page):
    """The MVP acceptance test's "ask JARVIS a question, get a real answer"
    step. This is the one test in the suite that always pays the full LLM
    latency cost end to end, by design."""
    logged_in_page("ADMIN")
    page.fill("#input", "In one short sentence, what is 2+2?")
    page.click("button:has-text('Send')")
    expect(page.locator("#log")).to_contain_text("answer", timeout=60000)
