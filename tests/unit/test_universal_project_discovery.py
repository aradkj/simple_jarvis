"""Unit tests for Universal Project and Directory Discovery in JARVIS.

Tests dynamic project discovery across drive roots, Docker directories,
Git remote inspections, manifest parsing, technology detection, and canonical matching.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.files.project_resolver import ProjectResolver


@pytest.fixture
def resolver(tmp_path: Path) -> ProjectResolver:
    res = ProjectResolver()
    pc_shop_dir = tmp_path / "pc-shop"
    pc_shop_dir.mkdir(parents=True, exist_ok=True)
    (pc_shop_dir / ".git").mkdir(exist_ok=True)
    (pc_shop_dir / "package.json").write_text('{"name": "pc-shop"}', encoding="utf-8")

    warehouse_dir = tmp_path / "warehouse"
    warehouse_dir.mkdir(parents=True, exist_ok=True)
    (warehouse_dir / ".git").mkdir(exist_ok=True)
    (warehouse_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (warehouse_dir / "README.md").write_text(
        "# Warehouse Management\nBuilt with FastAPI and SQLAlchemy", encoding="utf-8"
    )

    ocr_dir = tmp_path / "OCR"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    (ocr_dir / ".git").mkdir(exist_ok=True)
    (ocr_dir / "README.md").write_text(
        "# Document Processing Platform\nOCR engine", encoding="utf-8"
    )

    jarvis_dir = tmp_path / "jarvis"
    jarvis_dir.mkdir(parents=True, exist_ok=True)
    (jarvis_dir / ".git").mkdir(exist_ok=True)
    (jarvis_dir / "pyproject.toml").write_text(
        '[project]\nname = "jarvis"\ndescription = "JARVIS Personal AI Agent"\ndependencies = ["fastapi", "pyside6"]\n',
        encoding="utf-8",
    )

    res.get_candidate_roots = lambda: [tmp_path, Path.cwd()]
    res._cached_projects.clear()
    return res


def test_pc_shop_project_discovery(resolver: ProjectResolver) -> None:
    """Diagnostic test: JARVIS must dynamically discover PC Shop at C:\\docker\\pc-shop."""
    queries = [
        "PC Shop project",
        "pc-shop",
        "PC Shop",
        "پروژه پیسی شاپ",
        "پروژه پیسیشاپ",
    ]
    for q in queries:
        proj = resolver.resolve_project(q)
        assert proj is not None, f"Failed to resolve project for query: {q}"
        assert "pc-shop" in proj.name.lower() or "pc-shop" in str(proj.path).lower()
        assert Path(proj.path).exists()
        assert Path(proj.path).is_dir()
        assert proj.is_git is True


def test_warehouse_project_discovery(resolver: ProjectResolver) -> None:
    """Diagnostic test: JARVIS must dynamically discover warehouse at C:\\docker\\warehouse."""
    queries = [
        "warehouse project",
        "warehouse",
        "پروژه انبار",
    ]
    for q in queries:
        proj = resolver.resolve_project(q)
        assert proj is not None, f"Failed to resolve warehouse for query: {q}"
        assert "warehouse" in proj.name.lower() or "warehouse" in str(proj.path).lower()
        assert Path(proj.path).exists()
        assert Path(proj.path).is_dir()


def test_document_processing_ocr_discovery(resolver: ProjectResolver) -> None:
    """Diagnostic test: Document processing project resolves to C:\\docker\\OCR via README/Git."""
    queries = [
        "document processing project",
        "document processing platform",
        "پروژه پردازش اسناد",
        "پروژه پردازش سند",
    ]
    for q in queries:
        proj = resolver.resolve_project(q)
        assert proj is not None, f"Failed to resolve document processing for query: {q}"
        assert (
            "ocr" in proj.name.lower()
            or "ocr" in str(proj.path).lower()
            or "document" in proj.description.lower()
        )
        assert Path(proj.path).exists()


def test_fastapi_technology_discovery(resolver: ProjectResolver) -> None:
    """Diagnostic test: Discovering projects by technology keyword (FastAPI)."""
    proj = resolver.resolve_project("Python project that contains FastAPI")
    assert proj is not None
    assert "fastapi" in proj.technologies
    assert Path(proj.path).exists()


def test_jarvis_project_discovery(resolver: ProjectResolver) -> None:
    """Diagnostic test: Current workspace project discovery."""
    proj = resolver.resolve_project("JARVIS")
    assert proj is not None
    assert "jarvis" in proj.name.lower() or "jarvis" in str(proj.path).lower()
    assert Path(proj.path).exists()


def test_canonical_key_normalization() -> None:
    """Verify separator-insensitive canonical key generation."""
    assert ProjectResolver.canonical_key("PC Shop") == "pcshop"
    assert ProjectResolver.canonical_key("pc-shop") == "pcshop"
    assert ProjectResolver.canonical_key("pc_shop") == "pcshop"
    assert ProjectResolver.canonical_key("پیسی شاپ") == "pcshop"
    assert ProjectResolver.canonical_key("انبار") == "warehouse"


def test_nonexistent_project_returns_none(resolver: ProjectResolver) -> None:
    """Non-existent project queries must return None without infinite loops."""
    res = resolver.resolve_project("non_existent_project_xyz_9999")
    assert res is None


def test_project_metadata_richness(resolver: ProjectResolver) -> None:
    """Discovered projects should carry rich metadata (technologies, description, git remote)."""
    all_projects = resolver.scan_nearby_projects()
    assert len(all_projects) > 0

    # Verify at least one project has git metadata and markers
    found_git = any(p.is_git for p in all_projects.values())
    assert found_git is True
