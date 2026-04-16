"""
Application configuration loaded from environment variables.
"""
import os
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # Supabase
    supabase_url: str = Field(default="https://foijpyqxfqlsugjzjtef.supabase.co")
    supabase_key: str = Field(default="")
    supabase_db_url: str = Field(default="")

    # LLM
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.1:8b")
    groq_api_key: str = Field(default="")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Qdrant
    qdrant_url: str = Field(default="http://localhost:6333")

    # App
    app_env: str = Field(default="development")
    log_level: str = Field(default="DEBUG")
    upload_dir: str = Field(default="./uploads")

    # Monitoring
    prometheus_enabled: bool = Field(default=True)

    # Mailtrap (Evidence Coordinator)
    mailtrap_api_key: str = Field(default="")
    mailtrap_sender_email: str = Field(default="opus@vrm-system.com")
    mailtrap_sender_name: str = Field(default="OPUS Vendor Risk System")
    mailgun_api_key: str = Field(default="")
    mailgun_domain: str = Field(default="")
    mailgun_base_url: str = Field(default="https://api.mailgun.net/v3")

    # Credit Rating API
    credit_api_mode: str = Field(default="mock")  # "mock" or "opencorporates"
    opencorporates_api_key: str = Field(default="")

    # JWT Auth
    jwt_secret: str = Field(default="")  # Set to enable authentication

    # Phase 3 Workflow
    auto_simulate_approvals: bool = Field(default=False)
    max_workflow_retries: int = Field(default=2)

    # Risk thresholds — used by approval orchestrator auto-simulation
    risk_threshold_high: float = Field(default=80.0)
    risk_threshold_medium: float = Field(default=60.0)
    risk_threshold_low: float = Field(default=40.0)

    # Rate limiting & timeout (Groq free tier = 30 RPM)
    llm_requests_per_minute: int = Field(default=25)
    agent_timeout_seconds: int = Field(default=120)

    model_config = {

        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
