"""Unit tests for Windows filesystem reliability, Known Folder APIs, and directory creation."""

import shutil
import tempfile
from pathlib import Path

import pytest

from infrastructure.paths import (
    get_desktop_dir,
    get_documents_dir,
    get_downloads_dir,
    resolve_destination_directory,
)
from tools.filesystem.file_service import FileService
from tools.filesystem.file_tools import FileCreateDirectoryTool
from tools.filesystem.path_security import PathSecurityService


class TestKnownFolderResolution:
    """Test native Win32 Known Folder API resolution and fallbacks."""

    def test_get_desktop_dir(self):
        desktop = get_desktop_dir()
        assert desktop is not None
        assert isinstance(desktop, Path)
        assert desktop.exists()
        assert desktop.is_dir()
        assert "desktop" in str(desktop).lower()

    def test_get_documents_dir(self):
        docs = get_documents_dir()
        assert docs is not None
        assert isinstance(docs, Path)
        assert docs.exists()
        assert docs.is_dir()

    def test_get_downloads_dir(self):
        downloads = get_downloads_dir()
        assert downloads is not None
        assert isinstance(downloads, Path)
        assert downloads.exists()
        assert downloads.is_dir()

    def test_resolve_destination_directory_keywords(self):
        assert resolve_destination_directory("desktop") == get_desktop_dir()
        assert resolve_destination_directory("دسکتاپ") == get_desktop_dir()
        assert resolve_destination_directory("میزکار") == get_desktop_dir()

        assert resolve_destination_directory("documents") == get_documents_dir()
        assert resolve_destination_directory("داکیومنت") == get_documents_dir()
        assert resolve_destination_directory("اسناد") == get_documents_dir()

        assert resolve_destination_directory("downloads") == get_downloads_dir()
        assert resolve_destination_directory("دانلود") == get_downloads_dir()


class TestFileServiceCreateDirectory:
    """Test directory creation, idempotence, security, and Unicode/Persian support."""

    @pytest.fixture
    def setup_env(self):
        tmp = tempfile.mkdtemp(prefix="jarvis_fs_test_")
        security = PathSecurityService()
        security.add_directory(str(tmp), display_name="TestTemp")
        service = FileService(security_service=security)
        yield Path(tmp), service
        shutil.rmtree(tmp, ignore_errors=True)

    def test_create_directory_success(self, setup_env):
        test_root, service = setup_env
        target = test_root / "NewFolder"
        res = service.create_directory(target)

        assert res.success is True
        assert res.already_exists is False
        assert target.exists()
        assert target.is_dir()
        assert res.data["directory_path"] == str(target.resolve())

    def test_create_directory_idempotence(self, setup_env):
        test_root, service = setup_env
        target = test_root / "ExistingFolder"
        target.mkdir()

        res = service.create_directory(target, exist_ok=True)
        assert res.success is True
        assert res.already_exists is True
        assert target.exists()

    def test_create_nested_directory(self, setup_env):
        test_root, service = setup_env
        nested = test_root / "Parent" / "Child" / "Grandchild"
        res = service.create_directory(nested, parents=True)

        assert res.success is True
        assert nested.exists()
        assert nested.is_dir()

    def test_create_persian_unicode_directory(self, setup_env):
        test_root, service = setup_env
        persian_dir = test_root / "پروژه‌های پایتون جارویس"
        res = service.create_directory(persian_dir)

        assert res.success is True
        assert persian_dir.exists()
        assert persian_dir.is_dir()

    def test_create_directory_with_spaces(self, setup_env):
        test_root, service = setup_env
        spaced_dir = test_root / "JARVIS Test Folder With Spaces"
        res = service.create_directory(spaced_dir)

        assert res.success is True
        assert spaced_dir.exists()

    def test_reserved_windows_name_rejection(self, setup_env):
        test_root, service = setup_env
        for reserved in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1"):
            res = service.create_directory(test_root / reserved)
            assert res.success is False
            assert "reserved" in (res.error or "").lower()

    def test_create_directory_over_existing_file(self, setup_env):
        test_root, service = setup_env
        file_path = test_root / "some_file.txt"
        file_path.write_text("hello", encoding="utf-8")

        res = service.create_directory(file_path)
        assert res.success is False
        assert "cannot create directory" in (res.error or "").lower()


class TestPathSecurityDirectoryCreation:
    """Test PathSecurityService directory creation scoping."""

    def test_allowed_desktop_directory_creation(self):
        security = PathSecurityService()
        desktop = get_desktop_dir()
        target = desktop / "SafeFolderTest_12345"

        # Directory creation should be permitted under desktop
        resolved = security.validate_and_resolve_path(
            str(target),
            operation="create_directory",
        )
        assert resolved == target.resolve()

    def test_path_traversal_blocked(self):
        security = PathSecurityService()
        with pytest.raises((PermissionError, ValueError)):
            security.validate_and_resolve_path(
                r"C:\Windows\System32\malicious_folder",
                operation="create_directory",
            )


class TestFileCreateDirectoryTool:
    """Test FileCreateDirectoryTool definition and execution."""

    @pytest.fixture
    def setup_tool_env(self):
        tmp = tempfile.mkdtemp(prefix="jarvis_tool_test_")
        security = PathSecurityService()
        security.add_directory(str(tmp), display_name="ToolTemp")
        service = FileService(security_service=security)
        yield Path(tmp), service
        shutil.rmtree(tmp, ignore_errors=True)

    def test_tool_definition(self):
        tool = FileCreateDirectoryTool()
        defn = tool.get_definition()
        assert defn.name == "file_create_directory"
        assert defn.requires_approval is False
        assert "directory_path" in defn.parameters_schema.get("properties", {})

    def test_tool_execution(self, setup_tool_env):
        test_root, service = setup_tool_env
        tool = FileCreateDirectoryTool(file_service=service)
        target = test_root / "ToolCreatedDir"

        result = tool.execute(directory_path=str(target))
        assert result.status.value == "success"
        assert result.data["already_exists"] is False
        assert target.exists()
        assert target.is_dir()
