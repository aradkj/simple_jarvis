"""Unit tests for Windows application discovery, resolution, validation, and launch reliability."""

from pathlib import Path
from unittest.mock import patch

import pytest

from tools.windows.discovery import (
    WindowsApplicationDiscovery,
    get_windows_app_discovery,
    is_generic_coding_request,
)
from tools.windows.exceptions import ApplicationNotFoundError, TargetValidationError
from tools.windows.models import WindowInfo, WindowState
from tools.windows.target_validation import TargetValidator
from tools.windows.windows_service import WindowsControlService


class TestVSCodeResolution:
    """Test dynamic resolution of Visual Studio Code executable."""

    def test_resolve_vscode_executable_on_host(self):
        disc = get_windows_app_discovery()
        exe = disc.resolve_vscode_executable()
        assert exe is not None
        assert isinstance(exe, Path)
        assert exe.is_file()
        assert exe.name.lower() in ("code.exe", "code")

    def test_resolve_vscode_executable_fallback_order(self):
        disc = WindowsApplicationDiscovery()
        with patch.object(Path, "is_file", return_value=True):
            resolved = disc.resolve_vscode_executable()
            assert resolved is not None
            assert "Code.exe" in str(resolved)

    def test_target_validator_resolves_cmd_wrapper(self):
        # Even if passed 'code.cmd', TargetValidator resolves to Code.exe via which/parent
        resolved = TargetValidator.validate_executable_path("code.cmd")
        assert resolved.suffix.lower() == ".exe"
        assert resolved.is_file()

    def test_target_validator_rejects_missing_file(self):
        with pytest.raises(TargetValidationError):
            TargetValidator.validate_executable_path("C:\\AI\\non_existent_fake_app_123.exe")


class TestWindowsControlServiceResolution:
    """Test WindowsControlService application resolution for VS Code and aliases."""

    @pytest.fixture
    def service(self):
        return WindowsControlService()

    def test_resolve_code_aliases(self, service):
        for alias in (
            "code",
            "vscode",
            "visual studio code",
            "visualstudiocode",
            "ویژوال استودیو کد",
        ):
            app_info = service.resolve_application(alias)
            assert app_info.app_id in ("code", "vscode")
            assert app_info.is_installed is True
            assert app_info.executable_path.lower().endswith("code.exe")
            assert Path(app_info.executable_path).is_file()

    def test_resolve_unknown_application_raises(self, service):
        with pytest.raises(ApplicationNotFoundError):
            service.resolve_application("completely_fake_app_xyz_999")

    def test_find_windows_flexible_matching(self, service):
        fake_window = WindowInfo(
            hwnd=12345,
            title="● main.py - jarvis - Visual Studio Code",
            class_name="Chrome_WidgetWin_1",
            pid=9999,
            process_name="Code.exe",
            state=WindowState.NORMAL,
            is_visible=True,
        )
        with patch.object(service, "list_windows", return_value=[fake_window]):
            # Match by app_name "visual studio code"
            matches = service.find_windows(app_name="visual studio code")
            assert len(matches) == 1
            assert matches[0].hwnd == 12345

            # Match by app_name "code"
            matches_code = service.find_windows(app_name="code")
            assert len(matches_code) == 1

            # Match by query substring
            matches_q = service.find_windows(query="main.py")
            assert len(matches_q) == 1


class TestGenericCodingDetection:
    """Test generic and implied coding intent detection."""

    def test_generic_coding_cues(self):
        assert is_generic_coding_request("I need to code now") is True
        assert is_generic_coding_request("Let's start programming") is True
        assert is_generic_coding_request("time to code") is True
        assert is_generic_coding_request("open a coding environment") is True
        assert is_generic_coding_request("میخوام کدنویسی کنم") is True
        assert is_generic_coding_request("بریم کد بزنیم") is True
        assert is_generic_coding_request("محیط کدنویسی رو باز کن") is True

    def test_specific_editor_not_generic(self):
        # Specific mentions should not be marked as generic
        assert is_generic_coding_request("Open VS Code") is False
        assert is_generic_coding_request("Launch Cursor") is False
