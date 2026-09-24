"""Configuration management for ODIS Obliterator."""

from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    # Server settings
    host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("CONTROLLER_HOST", "HOST", "host"),
        description="Host interface for Controller API server.",
    )
    port: int = Field(
        default=8000,
        validation_alias=AliasChoices("CONTROLLER_PORT", "PORT", "port"),
        description="Port for Controller API server.",
    )

    # Kelpie / AI Gateway settings
    kelpie_base_url: str = Field(
        default="https://oauth.ai.container.edag",
        validation_alias=AliasChoices("KELPIE_BASE_URL", "kelpie_base_url"),
        description="Kelpie Gateway base URL.",
    )
    kelpie_proxy_url: str = Field(
        default="http://127.0.0.1:18080",
        validation_alias=AliasChoices("KELPIE_PROXY_URL", "kelpie_proxy_url"),
        description="Local Kelpie reverse proxy URL.",
    )
    kelpie_model: str = Field(
        default="gemini-3.7-flash",
        validation_alias=AliasChoices("KELPIE_MODEL", "DEFAULT_MODEL", "kelpie_model"),
        description="Default multimodal model for vision engine.",
    )
    timeout: float = Field(
        default=60.0,
        validation_alias=AliasChoices("TIMEOUT", "REQUEST_TIMEOUT", "timeout"),
        description="Default request timeout in seconds.",
    )

    # Execution & Domain settings
    dry_run: bool = Field(
        default=False,
        validation_alias=AliasChoices("DRY_RUN", "dry_run"),
        description="Dry run mode (no permanent modifications to ODIS).",
    )
    target_keyword: str = Field(
        default="Lamborghini",
        validation_alias=AliasChoices("TARGET_KEYWORD", "target_keyword"),
        description="Target keyword to sanitize from GFF blocks.",
    )
    version_comment: str = Field(
        default="Removed Lamborghini labels",
        validation_alias=AliasChoices("VERSION_COMMENT", "version_comment"),
        description="Standard version comment for modified objects.",
    )

    # Worker settings
    worker_poll_interval: float = Field(
        default=1.0,
        validation_alias=AliasChoices("WORKER_POLL_INTERVAL", "worker_poll_interval"),
        description="Polling interval in seconds for the worker agent.",
    )
    controller_api_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias=AliasChoices("CONTROLLER_API_URL", "controller_api_url"),
        description="URL of the Controller API as seen by the Worker.",
    )
    action_delay: float = Field(
        default=0.5,
        validation_alias=AliasChoices("ACTION_DELAY", "action_delay"),
        description="Delay in seconds between UI automation actions.",
    )

    # Paths & Files
    base_dir: Path = Field(
        default_factory=lambda: PROJECT_ROOT,
        description="Project root directory path.",
    )
    data_dir_override: Optional[Path] = Field(
        default=None,
        validation_alias=AliasChoices("DATA_DIR", "data_dir", "data_dir_override"),
        description="Custom directory path for data files.",
    )
    logs_dir_override: Optional[Path] = Field(
        default=None,
        validation_alias=AliasChoices("LOGS_DIR", "logs_dir", "logs_dir_override"),
        description="Custom directory path for log files.",
    )
    assets_dir_override: Optional[Path] = Field(
        default=None,
        validation_alias=AliasChoices("ASSETS_DIR", "assets_dir", "assets_dir_override"),
        description="Custom directory path for assets.",
    )
    input_gff_override: Optional[Path] = Field(
        default=None,
        validation_alias=AliasChoices("INPUT_GFF_PATH", "input_gff_path", "input_gff_override"),
        description="Custom path to the input GFF file.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def data_dir(self) -> Path:
        """Resolved data directory."""
        if self.data_dir_override is not None:
            return self.data_dir_override
        return self.base_dir / "data"

    @property
    def logs_dir(self) -> Path:
        """Resolved logs directory."""
        if self.logs_dir_override is not None:
            return self.logs_dir_override
        return self.base_dir / "logs"

    @property
    def assets_dir(self) -> Path:
        """Resolved assets directory."""
        if self.assets_dir_override is not None:
            return self.assets_dir_override
        return self.base_dir / "assets"

    @property
    def icons_dir(self) -> Path:
        """Resolved icons directory."""
        return self.assets_dir / "icons"

    @property
    def input_gff_path(self) -> Path:
        """Resolved input GFF file path."""
        if self.input_gff_override is not None:
            return self.input_gff_override
        return self.data_dir / "input_gff.txt"


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()


def reload_settings() -> Settings:
    """Clear cache and return a newly loaded Settings instance."""
    get_settings.cache_clear()
    return get_settings()


# Global settings instance
settings = get_settings()
