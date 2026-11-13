"""Path management utilities for JARVIS."""

from pathlib import Path


def get_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """Return the path to the persistent data directory, ensuring it exists."""
    data_dir = get_project_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_logs_dir() -> Path:
    """Return the path to the log directory, ensuring it exists."""
    logs_dir = get_project_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_docs_dir() -> Path:
    """Return the path to the documentation directory."""
    return get_project_root() / "docs"


def ensure_directory(path: Path) -> Path:
    """Ensure a directory exists and return its resolved path."""
    resolved = path.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
