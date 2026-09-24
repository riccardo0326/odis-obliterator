"""Unit tests for configuration management and project scaffolding (TASK-001)."""

import os
from pathlib import Path
import pytest
from controller.config import Settings, get_settings, reload_settings, PROJECT_ROOT


@pytest.fixture(autouse=True)
def reset_settings_after_test():
    """Ensure global settings cache is fresh before and after each test."""
    reload_settings()
    yield
    reload_settings()


def test_default_settings():
    """Verify default configuration parameters."""
    config = Settings()
    assert config.host == "0.0.0.0"
    assert config.port == 8000
    assert config.kelpie_base_url == "https://oauth.ai.container.edag"
    assert config.kelpie_proxy_url == "http://127.0.0.1:18080"
    assert config.kelpie_model == "gemini-3.7-flash"
    assert config.timeout == 60.0
    assert config.dry_run is False
    assert config.target_keyword == "Lamborghini"
    assert config.version_comment == "Removed Lamborghini labels"
    assert config.worker_poll_interval == 1.0
    assert config.controller_api_url == "http://127.0.0.1:8000"
    assert config.action_delay == 0.5


def test_default_paths():
    """Verify default directory and file path resolutions."""
    config = Settings()
    assert config.base_dir == PROJECT_ROOT
    assert config.data_dir == PROJECT_ROOT / "data"
    assert config.logs_dir == PROJECT_ROOT / "logs"
    assert config.assets_dir == PROJECT_ROOT / "assets"
    assert config.icons_dir == PROJECT_ROOT / "assets" / "icons"
    assert config.input_gff_path == PROJECT_ROOT / "data" / "input_gff.txt"


def test_custom_path_overrides():
    """Verify custom directory and file path overrides."""
    custom_data = Path("/custom/data")
    custom_logs = Path("/custom/logs")
    custom_assets = Path("/custom/assets")
    custom_gff = Path("/custom/my_gff.txt")

    config = Settings(
        data_dir_override=custom_data,
        logs_dir_override=custom_logs,
        assets_dir_override=custom_assets,
        input_gff_override=custom_gff,
    )
    assert config.data_dir == custom_data
    assert config.logs_dir == custom_logs
    assert config.assets_dir == custom_assets
    assert config.icons_dir == custom_assets / "icons"
    assert config.input_gff_path == custom_gff


def test_environment_variable_overrides(monkeypatch):
    """Verify configuration loading with custom environment variables."""
    monkeypatch.setenv("CONTROLLER_HOST", "192.168.1.100")
    monkeypatch.setenv("CONTROLLER_PORT", "9090")
    monkeypatch.setenv("KELPIE_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("TIMEOUT", "45.5")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("TARGET_KEYWORD", "CustomBrand")
    monkeypatch.setenv("VERSION_COMMENT", "Custom version comment")
    monkeypatch.setenv("WORKER_POLL_INTERVAL", "2.5")
    monkeypatch.setenv("CONTROLLER_API_URL", "http://192.168.1.100:9090")
    monkeypatch.setenv("ASSETS_DIR", "/custom/assets/dir")

    config = reload_settings()
    assert config.host == "192.168.1.100"
    assert config.port == 9090
    assert config.kelpie_model == "gemini-3.8-flash"
    assert config.timeout == 45.5
    assert config.dry_run is True
    assert config.target_keyword == "CustomBrand"
    assert config.version_comment == "Custom version comment"
    assert config.worker_poll_interval == 2.5
    assert config.controller_api_url == "http://192.168.1.100:9090"
    assert config.assets_dir == Path("/custom/assets/dir")
    assert config.icons_dir == Path("/custom/assets/dir/icons")

    # Reset
    reload_settings()


def test_alternative_env_aliases(monkeypatch):
    """Verify alternative environment variable names (HOST, PORT, DEFAULT_MODEL, REQUEST_TIMEOUT)."""
    monkeypatch.setenv("HOST", "10.0.0.1")
    monkeypatch.setenv("PORT", "8888")
    monkeypatch.setenv("DEFAULT_MODEL", "gpt-5.6-luna-gwc")
    monkeypatch.setenv("REQUEST_TIMEOUT", "120.0")

    config = reload_settings()
    assert config.host == "10.0.0.1"
    assert config.port == 8888
    assert config.kelpie_model == "gpt-5.6-luna-gwc"
    assert config.timeout == 120.0

    # Reset
    reload_settings()


def test_get_settings_caching():
    """Verify get_settings returns cached instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_project_scaffolding_structure():
    """Verify required project directories and package init files exist."""
    assert (PROJECT_ROOT / "controller").is_dir()
    assert (PROJECT_ROOT / "controller" / "__init__.py").is_file()
    assert (PROJECT_ROOT / "controller" / "config.py").is_file()

    assert (PROJECT_ROOT / "worker").is_dir()
    assert (PROJECT_ROOT / "worker" / "__init__.py").is_file()

    assert (PROJECT_ROOT / "data").is_dir()
    assert (PROJECT_ROOT / "data" / "input_gff.txt").is_file()

    assert (PROJECT_ROOT / "logs").is_dir()
    assert (PROJECT_ROOT / "assets").is_dir()
    assert (PROJECT_ROOT / "assets" / "icons").is_dir()
    assert (PROJECT_ROOT / "tests").is_dir()
    assert (PROJECT_ROOT / "tests" / "__init__.py").is_file()


def test_requirements_file_exists_and_contains_dependencies():
    """Verify requirements.txt is present and defines required libraries."""
    req_path = PROJECT_ROOT / "requirements.txt"
    assert req_path.exists()

    content = req_path.read_text(encoding="utf-8").lower()
    required_packages = [
        "fastapi",
        "uvicorn",
        "pydantic",
        "pillow",
        "pyautogui",
        "requests",
        "pytest",
    ]
    for pkg in required_packages:
        assert pkg in content, f"Missing {pkg} in requirements.txt"
