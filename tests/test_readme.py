"""Unit tests for User Documentation, Setup Guide and Network Configuration (TASK-010).

Validates that README.md provides comprehensive, rigorous operational documentation
covering PC EDAG Controller setup, PC Lamborghini Worker setup, GFF queue configuration,
Dry-Run vs Production modes, structured logging/reporting, and troubleshooting.
"""

from pathlib import Path
import pytest

from controller.config import PROJECT_ROOT


@pytest.fixture
def readme_content() -> str:
    """Fixture to load README.md content."""
    readme_path = PROJECT_ROOT / "README.md"
    assert readme_path.is_file(), f"README.md does not exist at {readme_path}"
    content = readme_path.read_text(encoding="utf-8")
    assert len(content) > 1000, "README.md is too short or empty"
    return content


def test_readme_file_exists_and_has_structure(readme_content: str):
    """Verify README.md exists and contains main architectural sections."""
    assert "# ODIS Obliterator" in readme_content
    assert "## Indice dei Contenuti" in readme_content
    assert "## 1. Panoramica e Obiettivo del Progetto" in readme_content
    assert "## 2. Architettura Distribuita & Topologia di Rete" in readme_content
    assert "## 3. Setup Ambiente su PC EDAG (Controller & AI Brain)" in readme_content
    assert "## 4. Setup Ambiente su PC Lamborghini (Worker UI)" in readme_content
    assert "## 5. Guida Operativa: Esecuzione del Batch" in readme_content
    assert "## 6. Workflow Operativo End-to-End (14 Passaggi)" in readme_content
    assert "## 7. Logging, Reportistica & Ripristino Sessione (Resume)" in readme_content
    assert "## 8. Risoluzione dei Problemi Comuni (Troubleshooting)" in readme_content
    assert "## 9. Esecuzione dei Test Unitari e di Integrazione" in readme_content


def test_readme_covers_edag_controller_setup(readme_content: str):
    """Verify PC EDAG setup instructions for Kelpie, Gemini vision model, and FastAPI server."""
    content_lower = readme_content.lower()

    # Kelpie Gateway & Model
    assert "kelpie" in content_lower
    assert "gemini-3.7-flash" in content_lower
    assert "kelpie auth login" in content_lower or "kelpie serve" in content_lower
    assert "18080" in readme_content

    # FastAPI Uvicorn binding
    assert "uvicorn" in content_lower
    assert "0.0.0.0" in readme_content
    assert "8000" in readme_content
    assert "/api/v1/health" in readme_content
    assert "/docs" in readme_content or "swagger" in content_lower


def test_readme_covers_lamborghini_worker_setup(readme_content: str):
    """Verify PC Lamborghini Worker setup instructions and ODIS Creator readiness."""
    content_lower = readme_content.lower()

    assert "worker" in content_lower
    assert "lamborghini" in content_lower
    assert "odis creator" in content_lower
    assert "requirements.txt" in readme_content
    assert "--health-only" in readme_content
    assert "--controller-url" in readme_content


def test_readme_covers_gff_queue_instructions(readme_content: str):
    """Verify documentation for preparing input_gff.txt batch queue."""
    assert "data/input_gff.txt" in readme_content
    assert "A16_4LA_91____1_518_88_Check_battery" in readme_content


def test_readme_covers_dry_run_vs_production(readme_content: str):
    """Verify Dry-Run vs Live production execution instructions."""
    assert "--dry-run" in readme_content
    assert "--no-dry-run" in readme_content
    assert "Dry-Run" in readme_content
    assert "Produzione" in readme_content


def test_readme_covers_logging_and_resume(readme_content: str):
    """Verify logging artifacts and resume documentation."""
    assert "logs/" in readme_content or "/logs" in readme_content
    assert "summary.json" in readme_content
    assert "execution.log" in readme_content
    assert "state.json" in readme_content
    assert "errors/" in readme_content
    assert "resume" in readme_content.lower() or "ripristino" in readme_content.lower()


def test_readme_covers_troubleshooting_and_edge_cases(readme_content: str):
    """Verify troubleshooting table includes Validation error, NOT_FOUND, firewall, etc."""
    assert "Validation error" in readme_content
    assert "Firewall" in readme_content or "firewall" in readme_content
    assert "NOT_FOUND" in readme_content or "non trovata" in readme_content.lower()


def test_readme_covers_domain_invariants(readme_content: str):
    """Verify inviolability of tags and standard version comment."""
    assert "Removed Lamborghini labels" in readme_content
    assert "@[std]" in readme_content
    assert "%str_" in readme_content
