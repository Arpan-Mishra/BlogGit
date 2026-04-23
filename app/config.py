from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: SecretStr = Field(..., description="Anthropic API key")
    anthropic_model: str = Field(
        default="claude-sonnet-4-6", description="Claude model to use for drafting"
    )
    anthropic_intake_model: str = Field(
        default="claude-haiku-4-5-20251001", description="Claude model for intake questions"
    )

    # LangSmith
    langsmith_api_key: SecretStr = Field(..., description="LangSmith API key")
    langsmith_project: str = Field(default="techblogcopilot", description="LangSmith project name")
    langchain_tracing_v2: bool = Field(default=True)
    langchain_endpoint: str = Field(default="https://api.smith.langchain.com")

    # Supabase
    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_anon_key: SecretStr = Field(..., description="Supabase anon/public key")
    supabase_service_role_key: SecretStr = Field(
        ..., description="Supabase service role key (backend only)"
    )

    # Encryption
    blog_copilot_kek: SecretStr = Field(
        ..., description="Fernet key-encryption key (32-byte base64 string)"
    )

    # GitHub OAuth
    github_client_id: str = Field(..., description="GitHub OAuth app client ID")
    github_client_secret: SecretStr = Field(..., description="GitHub OAuth app client secret")
    github_oauth_redirect_uri: str = Field(..., description="GitHub OAuth callback URL")

    # Notion OAuth
    notion_client_id: str = Field(..., description="Notion OAuth app client ID")
    notion_client_secret: SecretStr = Field(..., description="Notion OAuth app client secret")
    notion_oauth_redirect_uri: str = Field(..., description="Notion OAuth callback URL")

    # LinkedIn OAuth (required when LinkedIn publishing is enabled)
    linkedin_client_id: str = Field(..., description="LinkedIn OAuth app client ID")
    linkedin_client_secret: SecretStr = Field(..., description="LinkedIn OAuth app client secret")
    linkedin_oauth_redirect_uri: str = Field(..., description="LinkedIn OAuth callback URL")

    # Web search (optional — enables research during blog post drafting)
    tavily_api_key: SecretStr | None = Field(
        default=None,
        description="Tavily API key for web search during drafting. Optional — drafting works without it.",
    )

    # Unsplash (optional — enables image search during drafting)
    unsplash_access_key: str | None = Field(
        default=None,
        description="Unsplash API access key for image search during drafting. Optional.",
    )

    # App
    app_secret_key: SecretStr = Field(..., description="Secret key for signing cookies/sessions")
    app_base_url: str = Field(
        default="http://localhost:8000", description="Base URL of the FastAPI backend"
    )
    frontend_url: str = Field(
        default="http://localhost:8501",
        description="Base URL of the Streamlit frontend (OAuth post-auth redirect destination)",
    )
    debug: bool = Field(default=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
