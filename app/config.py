"""Configuration and settings management using pydantic-settings."""

from typing import Optional
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Application settings loaded from environment variables."""

    # API
    debug: bool = False
    api_port: int = 8000
    api_host: str = "0.0.0.0"

    # Databases
    app_db_url: str  # Required: postgresql://user:pass@localhost/app_db
    target_db_url: str  # Required: postgresql://user:pass@localhost/target_db
    target_db_readonly_role: str = "querypilot_ro"

    # Agent
    max_retries: int = 3
    max_iterations: int = 10
    query_timeout_seconds: int = 5
    result_row_limit: int = 1000

    # LLM
    llm_provider: str  # Required: "openai", "anthropic", or "bedrock"
    llm_model: str  # Required: e.g., "gpt-4-turbo", "claude-3-opus", etc.
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048

    # LLM API Keys (provider-specific, optional based on provider)
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"

    # Observability
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None

    # Redis & Memory
    redis_url: Optional[str] = None
    memory_history_limit: int = 10  # Number of turns to load as short-term memory
    memory_long_term_enabled: bool = False  # Enable long-term few-shot examples
    memory_embedding_model: str = "text-embedding-3-small"  # For long-term memory
    memory_similarity_threshold: float = 0.6  # Similarity threshold for few-shot retrieval
    memory_summary_threshold: int = 20  # Summarize history when exceeds this

    class ConfigDict:
        """Pydantic v2 config."""

        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def validate_required_vars(self) -> None:
        """Validate that all required variables are set."""
        errors = []

        # Required database vars
        if not self.app_db_url:
            errors.append("Missing required env var: APP_DB_URL")
        if not self.target_db_url:
            errors.append("Missing required env var: TARGET_DB_URL")

        # Required LLM vars
        if not self.llm_provider:
            errors.append("Missing required env var: LLM_PROVIDER")
        if not self.llm_model:
            errors.append("Missing required env var: LLM_MODEL")

        # Provider-specific credential validation
        provider = self.llm_provider.lower() if self.llm_provider else None
        if provider == "openai" and not self.openai_api_key:
            errors.append("Missing required env var: OPENAI_API_KEY (for provider=openai)")
        if provider == "anthropic" and not self.anthropic_api_key:
            errors.append("Missing required env var: ANTHROPIC_API_KEY (for provider=anthropic)")
        if provider == "bedrock" and not (self.aws_access_key_id and self.aws_secret_access_key):
            errors.append(
                "Missing required env vars: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (for provider=bedrock)"
            )

        if errors:
            raise ValueError("\n".join(errors))

    def __init__(self, **data) -> None:
        """Initialize config and validate required vars."""
        super().__init__(**data)
        self.validate_required_vars()


# Singleton config instance (lazy-loaded on first use)
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the singleton config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
