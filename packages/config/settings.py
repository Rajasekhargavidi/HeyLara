"""Central runtime configuration, read once from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Docker Compose injects env vars directly; local `uvicorn` runs need .env
# loaded explicitly. Safe to call even when no .env file exists.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./jarvis.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-local-env")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
    jarvis_mode: str = os.getenv("JARVIS_MODE", "demo")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    ollama_embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    # --- LLM provider selection ---
    # "ollama" (default, fully local/free) or "groq" (free-tier cloud API,
    # needs GROQ_API_KEY — much larger/faster models, no longer offline).
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

    # --- Real social provider credentials (Phase 12) ---
    linkedin_client_id: str = os.getenv("LINKEDIN_CLIENT_ID", "")
    linkedin_client_secret: str = os.getenv("LINKEDIN_CLIENT_SECRET", "")
    linkedin_redirect_uri: str = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/api/oauth/linkedin/callback")
    linkedin_access_token: str = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    linkedin_org_urn: str = os.getenv("LINKEDIN_ORG_URN", "")
    facebook_access_token: str = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
    facebook_page_id: str = os.getenv("FACEBOOK_PAGE_ID", "")
    instagram_business_account_id: str = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
    x_api_key: str = os.getenv("X_API_KEY", "")
    x_api_secret: str = os.getenv("X_API_SECRET", "")
    x_access_token: str = os.getenv("X_ACCESS_TOKEN", "")
    x_access_secret: str = os.getenv("X_ACCESS_SECRET", "")

    # --- Real employee-comms credentials (Phase 12) ---
    teams_tenant_id: str = os.getenv("TEAMS_TENANT_ID", "")
    teams_client_id: str = os.getenv("TEAMS_CLIENT_ID", "")
    teams_client_secret: str = os.getenv("TEAMS_CLIENT_SECRET", "")
    whatsapp_business_token: str = os.getenv("WHATSAPP_BUSINESS_TOKEN", "")
    whatsapp_phone_number_id: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    whatsapp_webhook_verify_token: str = os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "change-me-in-local-env")


settings = Settings()
