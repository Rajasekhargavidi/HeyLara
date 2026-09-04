"""Mock customer messages — zero-cost demo mode.

Per the spec's ZERO-COST DEMO MODE: "customer messages are sample
conversations." These are clearly-labeled fictional inbound messages used
to exercise the Customer Engagement Agent without any real social account.
"""
from __future__ import annotations

DEMO_CONVERSATIONS = [
    {
        "platform": "LINKEDIN",
        "customer_handle": "demo_prospect_1",
        "message": "Hi, what does LaraVisionX's TestPilot product actually do? Does it support Playwright?",
    },
    {
        "platform": "INSTAGRAM",
        "customer_handle": "demo_prospect_2",
        "message": "How much does Agent Studio cost per month? Do you offer a discount for startups?",
    },
    {
        "platform": "FACEBOOK",
        "customer_handle": "demo_customer_angry",
        "message": "This is unacceptable. I want a refund immediately, your support team has ignored me for a week.",
    },
    {
        "platform": "X",
        "customer_handle": "demo_partner_lead",
        "message": "We run a QA consultancy and would love to explore a partnership with LaraVisionX. Who should we talk to?",
    },
    {
        "platform": "LINKEDIN",
        "customer_handle": "demo_security_report",
        "message": "I think I found a security issue in how your login page handles sessions. Who do I report this to?",
    },
]
