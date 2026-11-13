"""Global pytest fixtures for JARVIS testing."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from config import Settings
from core.agent import JARVISAgent
from core.events import EventBus
from core.permissions import StrictDefaultDenyPermissionManager
from memory.database import SQLiteMemoryStore


@pytest.fixture(scope="session")
def qapp() -> Generator[QApplication, None, None]:
    """Ensure a single QApplication instance exists for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def temp_dirs() -> Generator[tuple[Path, Path], None, None]:
    """Provide temporary data and logs directories."""
    with tempfile.TemporaryDirectory() as tmp_data, tempfile.TemporaryDirectory() as tmp_logs:
        yield Path(tmp_data), Path(tmp_logs)


@pytest.fixture
def test_settings(temp_dirs: tuple[Path, Path]) -> Settings:
    """Provide a isolated test settings instance."""
    data_dir, logs_dir = temp_dirs
    return Settings(
        app_name="JARVIS-Test",
        app_version="0.1.0-test",
        app_env="testing",
        debug=True,
        log_level="DEBUG",
        data_dir=data_dir,
        logs_dir=logs_dir,
        gemini_api_key=None,
    )


@pytest.fixture
def test_memory(temp_dirs: tuple[Path, Path]) -> Generator[SQLiteMemoryStore, None, None]:
    """Provide an initialized SQLite memory store using a temporary file."""
    data_dir, _ = temp_dirs
    db_path = data_dir / "test_jarvis.db"
    store = SQLiteMemoryStore(db_path=db_path)
    store.initialize()
    yield store
    store.close()


@pytest.fixture
def test_agent(
    test_settings: Settings, test_memory: SQLiteMemoryStore
) -> Generator[JARVISAgent, None, None]:
    """Provide an initialized test agent."""
    event_bus = EventBus()
    permission_manager = StrictDefaultDenyPermissionManager()
    agent = JARVISAgent(
        settings=test_settings,
        permission_manager=permission_manager,
        memory_store=test_memory,
        event_bus=event_bus,
    )
    agent.initialize()
    yield agent
    agent.shutdown()
