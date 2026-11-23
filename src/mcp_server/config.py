"""Application settings loaded from environment variables and optional .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for DevTeam Skills MCP Server."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    mcp_transport: Literal["stdio", "streamable-http"] = Field(
        default="stdio",
        alias="MCP_TRANSPORT",
    )
    mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")  # noqa: S104
    port: int = Field(default=8000, ge=1, le=65535, alias="PORT")
    mcp_path: str = Field(default="/mcp", alias="MCP_PATH")

    mcp_api_key: SecretStr | None = Field(default=None, alias="MCP_API_KEY")
    allowed_origins: str = Field(default="", alias="ALLOWED_ORIGINS")

    skills_dir: Path = Field(default=Path("./skills_store"), alias="SKILLS_DIR")
    roles_config_path: Path = Field(
        default=Path("./config/roles.yaml"),
        alias="ROLES_CONFIG_PATH",
    )

    mcp_enable_native_skills: bool = Field(
        default=True,
        alias="MCP_ENABLE_NATIVE_SKILLS",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse comma-separated ALLOWED_ORIGINS into a clean list."""
        if not self.allowed_origins.strip():
            return []
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def api_key_value(self) -> str | None:
        """Return non-empty Bearer API key value if configured."""
        if self.mcp_api_key is None:
            return None
        value = self.mcp_api_key.get_secret_value().strip()
        return value or None


def get_settings() -> Settings:
    """Instantiate settings from the current environment."""
    return Settings()
