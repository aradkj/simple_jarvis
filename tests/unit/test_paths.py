"""Unit tests for path management utilities."""

from pathlib import Path

from infrastructure.paths import (
    ensure_directory,
    get_docs_dir,
    get_logs_dir,
    get_project_root,
)


def test_project_root() -> None:
    """Verify project root path exists and contains core files."""
    root = get_project_root()
    assert root.exists()
    assert (root / "app.py").exists()
    assert (root / "config.py").exists()


def test_logs_and_data_directories(temp_dirs: tuple[Path, Path]) -> None:
    """Verify directories are resolved and created on demand."""
    logs_dir = get_logs_dir()
    assert logs_dir.exists()
    assert logs_dir.is_dir()

    docs_dir = get_docs_dir()
    assert docs_dir.name == "docs"


def test_ensure_directory(tmp_path: Path) -> None:
    """Verify ensure_directory creates non-existent directory paths."""
    nested = tmp_path / "sub" / "deep" / "dir"
    assert not nested.exists()
    resolved = ensure_directory(nested)
    assert resolved.exists()
    assert resolved.is_dir()
