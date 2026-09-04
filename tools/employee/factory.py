"""Chooses a real employee-comms channel when credentials are configured,
otherwise falls back to the mock — mirrors tools/social's real-vs-mock
split. Per the spec: "If an API cannot perform a requested action, mark
the capability as unavailable and show a manual fallback" — here the
fallback is the mock channel plus a note that the real one isn't wired up,
rather than silently pretending nothing changed.
"""
from __future__ import annotations

from packages.config.settings import settings
from tools.employee.base import EmployeeChannel
from tools.mock.employee_mock import MockEmployeeChannel


def get_employee_channel(channel_name: str) -> tuple[EmployeeChannel, bool]:
    """Returns (channel, is_real). is_real=False means credentials are
    missing and the mock is standing in — callers should surface that."""
    if settings.jarvis_mode == "live":
        try:
            if channel_name == "teams":
                from tools.employee.teams_provider import TeamsProvider
                return TeamsProvider(), True
            if channel_name == "whatsapp":
                from tools.employee.whatsapp_provider import WhatsAppProvider
                return WhatsAppProvider(), True
        except RuntimeError:
            pass  # missing credentials — fall through to mock
    return MockEmployeeChannel(), False
