"""Comprehensive unit and security regression test suite for Phase 4 Real-World Tools."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.execution_context import CancellationToken, ExecutionContext
from tools.filesystem.file_tools import (
    DirectoryListInput,
    DirectoryListTool,
    FileMetadataInput,
    FileMetadataTool,
    FileReadTextInput,
    FileReadTextTool,
    FileSearchTextInput,
    FileSearchTextTool,
)
from tools.filesystem.path_security import PathSecurityService
from tools.system.system_service import WindowsSystemService
from tools.system.system_tools import (
    CPUInput,
    EmptyInput,
    NetworkInput,
    SystemCPUInfoTool,
    SystemDiskInfoTool,
    SystemMemoryInfoTool,
    SystemNetworkInfoTool,
    SystemOverviewTool,
)

# ==============================================================================
# 1. System Intelligence Unit Tests
# ==============================================================================


def test_system_service_cpu_info():
    """Verify CPU inspection returns valid real or mockable hardware metrics."""
    data = WindowsSystemService.get_cpu_info(sample_duration=0.05)
    assert "model" in data
    assert isinstance(data["logical_cores"], int) and data["logical_cores"] >= 1
    assert isinstance(data["physical_cores"], int) and data["physical_cores"] >= 1
    assert "architecture" in data
    assert isinstance(data["utilization_percent"], float)
    assert 0.0 <= data["utilization_percent"] <= 100.0


def test_system_service_memory_info():
    """Verify memory status returns valid physical and page file metrics."""
    data = WindowsSystemService.get_memory_info()
    assert data["total_bytes"] > 0
    assert data["available_bytes"] > 0
    assert data["used_bytes"] >= 0
    assert 0.0 <= data["utilization_percent"] <= 100.0
    assert data["total_gb"] > 0.0


def test_system_service_disk_info():
    """Verify disk inspection returns local partitions and usage."""
    data = WindowsSystemService.get_disk_info()
    assert "partitions" in data
    assert len(data["partitions"]) >= 1
    p0 = data["partitions"][0]
    assert "mount_point" in p0
    assert p0["total_bytes"] > 0
    assert p0["free_bytes"] > 0
    assert "aggregate" in data
    assert data["aggregate"]["total_gb"] > 0


def test_system_service_network_info():
    """Verify network inspection returns adapter status and honors privacy flags."""
    # 1. Default (MAC redacted)
    data_redacted = WindowsSystemService.get_network_info(expose_mac=False)
    assert "hostname" in data_redacted
    assert "adapters" in data_redacted
    for a in data_redacted["adapters"]:
        assert a["mac_address"] == "[Redacted for Privacy]"

    # 2. Expose MAC enabled
    data_exposed = WindowsSystemService.get_network_info(expose_mac=True)
    assert "adapters" in data_exposed
    # At least check structure validity


def test_system_service_overview():
    """Verify system overview consolidates machine metrics."""
    overview = WindowsSystemService.get_system_overview(expose_mac=False)
    assert "Windows" in overview["os"]
    assert "python_runtime" in overview
    assert "cpu_summary" in overview
    assert "memory_summary" in overview
    assert "disk_summary" in overview


def test_system_tools_execution_and_cancellation():
    """Verify system tools execute safely and respect cancellation tokens."""
    ctx = ExecutionContext()
    cpu_tool = SystemCPUInfoTool()
    mem_tool = SystemMemoryInfoTool()
    disk_tool = SystemDiskInfoTool()
    net_tool = SystemNetworkInfoTool()
    overview_tool = SystemOverviewTool()

    # Success executions
    res_cpu = cpu_tool.execute(CPUInput(sample_duration=0.05), ctx)
    assert res_cpu.status.value == "success"
    assert "logical_cores" in res_cpu.data

    res_mem = mem_tool.execute(EmptyInput(), ctx)
    assert res_mem.status.value == "success"
    assert res_mem.data["total_gb"] > 0

    res_disk = disk_tool.execute(EmptyInput(), ctx)
    assert res_disk.status.value == "success"

    res_net = net_tool.execute(NetworkInput(include_mac=False), ctx)
    assert res_net.status.value == "success"

    res_ov = overview_tool.execute(EmptyInput(), ctx)
    assert res_ov.status.value == "success"

    # Cancellation behavior
    cancel_token = CancellationToken()
    cancel_token.cancel()
    cancel_ctx = ExecutionContext(cancellation_token=cancel_token)

    res_cancel = cpu_tool.execute(CPUInput(), cancel_ctx)
    assert res_cancel.status.value == "cancelled"


# ==============================================================================
# 2. Path Containment & Security Service Unit Tests
# ==============================================================================


@pytest.fixture
def temp_secure_dir():
    """Create an isolated temporary directory for security testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir).resolve()
        sub = root / "authorized_sub"
        sub.mkdir()
        outside = root / "unauthorized_outside"
        outside.mkdir()

        # Create safe files
        (sub / "notes.txt").write_text("Hello Jarvis secure world", encoding="utf-8")
        (sub / "data.json").write_text('{"name": "test"}', encoding="utf-8")
        (sub / "code.py").write_text("print('safe code')", encoding="utf-8")

        # Create sensitive files
        (sub / ".env").write_text(
            "GEMINI_API_KEY=AIzaSySecret1234567890123456789012345", encoding="utf-8"
        )
        (sub / "id_rsa").write_text(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...", encoding="utf-8"
        )
        (sub / "passwords.txt").write_text("admin:supersecretpassword", encoding="utf-8")

        # Create outside file
        (outside / "private.txt").write_text("Outside authorized folder", encoding="utf-8")

        yield {"root": root, "authorized": sub, "unauthorized": outside}


def test_path_security_add_and_revoke_directory(temp_secure_dir):
    """Verify explicit directory authorization and persistence."""
    store_file = temp_secure_dir["root"] / "auth_store.json"
    sec = PathSecurityService(storage_path=store_file)

    auth_path = str(temp_secure_dir["authorized"])
    entry = sec.add_directory(auth_path, display_name="Test Folder")
    assert entry.path.lower() == auth_path.lower()
    assert len(sec.list_authorized_directories()) == 1

    # Revoke
    revoked = sec.revoke_directory(entry.directory_id)
    assert revoked is True
    assert len(sec.list_authorized_directories()) == 0


def test_path_traversal_rejection(temp_secure_dir):
    """Verify traversal attacks ('..', UNC, Alternate Data Streams) are strictly blocked."""
    store_file = temp_secure_dir["root"] / "auth_store.json"
    sec = PathSecurityService(storage_path=store_file)
    sec.add_directory(str(temp_secure_dir["authorized"]))

    # 1. Traversal outside root
    escape_path = str(temp_secure_dir["authorized"] / ".." / "unauthorized_outside" / "private.txt")
    with pytest.raises(PermissionError, match="outside all authorized directories"):
        sec.validate_and_resolve_path(escape_path)

    # 2. UNC path attempt
    with pytest.raises(PermissionError, match="Network shares and UNC paths are prohibited"):
        sec.validate_and_resolve_path(r"\\192.168.1.1\share\file.txt")

    # 3. Alternate Data Stream attempt
    with pytest.raises(PermissionError, match="Alternate Data Stream"):
        sec.validate_and_resolve_path(
            str(temp_secure_dir["authorized"] / "notes.txt:hidden_stream")
        )


def test_sensitive_file_denylist_enforcement(temp_secure_dir):
    """Sensitive files (.env, id_rsa, passwords.txt) must be denied even inside authorized directory."""
    store_file = temp_secure_dir["root"] / "auth_store.json"
    sec = PathSecurityService(storage_path=store_file)
    sec.add_directory(str(temp_secure_dir["authorized"]))

    # .env
    with pytest.raises(PermissionError, match="matches protected secret/credential denylist"):
        sec.validate_and_resolve_path(str(temp_secure_dir["authorized"] / ".env"))

    # id_rsa
    with pytest.raises(PermissionError, match="matches protected secret/credential denylist"):
        sec.validate_and_resolve_path(str(temp_secure_dir["authorized"] / "id_rsa"))

    # passwords.txt
    with pytest.raises(PermissionError, match="matches protected secret/credential denylist"):
        sec.validate_and_resolve_path(str(temp_secure_dir["authorized"] / "passwords.txt"))


def test_secret_redaction():
    """Verify secret patterns in text are redacted safely."""
    raw = "Here is my key: AIzaSyD9837429873498273498273498273498 and private password='supersecret123'"
    redacted = PathSecurityService.redact_secrets(raw)
    assert "[REDACTED_API_KEY]" in redacted
    assert "supersecret123" not in redacted
    assert "[REDACTED_SECRET]" in redacted


# ==============================================================================
# 3. Secure File Tools Unit Tests
# ==============================================================================


def test_file_list_directory_tool(temp_secure_dir):
    """Verify file_list_directory returns entries safely within authorized boundaries."""
    store_file = temp_secure_dir["root"] / "auth_store.json"
    sec = PathSecurityService(storage_path=store_file)
    sec.add_directory(str(temp_secure_dir["authorized"]))

    with patch("tools.filesystem.file_tools.get_path_security_service", return_value=sec):
        tool = DirectoryListTool()
        ctx = ExecutionContext()

        # Inside authorized
        res = tool.execute(
            DirectoryListInput(directory_path=str(temp_secure_dir["authorized"])), ctx
        )
        assert res.status.value == "success"
        entries = [e["name"] for e in res.data["entries"]]
        assert "notes.txt" in entries
        assert "data.json" in entries

        # Outside authorized
        res_denied = tool.execute(
            DirectoryListInput(directory_path=str(temp_secure_dir["unauthorized"])), ctx
        )
        assert res_denied.status.value == "denied"
        assert "outside all authorized directories" in res_denied.error


def test_file_read_text_tool_success_and_safety(temp_secure_dir):
    """Verify file_read_text reads valid text files and blocks denied/binary files."""
    store_file = temp_secure_dir["root"] / "auth_store.json"
    sec = PathSecurityService(storage_path=store_file)
    sec.add_directory(str(temp_secure_dir["authorized"]))

    with patch("tools.filesystem.file_tools.get_path_security_service", return_value=sec):
        tool = FileReadTextTool()
        ctx = ExecutionContext()

        # Safe read
        res = tool.execute(
            FileReadTextInput(file_path=str(temp_secure_dir["authorized"] / "notes.txt")), ctx
        )
        assert res.status.value == "success"
        assert res.data["content"] == "Hello Jarvis secure world"

        # Denied extension (e.g. .exe)
        exe_file = temp_secure_dir["authorized"] / "test.exe"
        exe_file.write_bytes(b"\x00\x01\x02\x03")
        res_ext = tool.execute(FileReadTextInput(file_path=str(exe_file)), ctx)
        assert res_ext.status.value == "denied"
        assert "not in the allowed text extensions list" in res_ext.error

        # Denied sensitive file
        res_env = tool.execute(
            FileReadTextInput(file_path=str(temp_secure_dir["authorized"] / ".env")), ctx
        )
        assert res_env.status.value == "denied"
        assert "matches protected secret/credential denylist" in res_env.error


def test_file_metadata_tool(temp_secure_dir):
    """Verify file_get_metadata extracts size and modification timestamps."""
    store_file = temp_secure_dir["root"] / "auth_store.json"
    sec = PathSecurityService(storage_path=store_file)
    sec.add_directory(str(temp_secure_dir["authorized"]))

    with patch("tools.filesystem.file_tools.get_path_security_service", return_value=sec):
        tool = FileMetadataTool()
        ctx = ExecutionContext()

        res = tool.execute(
            FileMetadataInput(file_path=str(temp_secure_dir["authorized"] / "notes.txt")), ctx
        )
        assert res.status.value == "success"
        assert res.data["filename"] == "notes.txt"
        assert res.data["size_bytes"] > 0
        assert res.data["extension"] == ".txt"


def test_file_search_text_tool_bounded(temp_secure_dir):
    """Verify file_search_text safely discovers matching phrases."""
    store_file = temp_secure_dir["root"] / "auth_store.json"
    sec = PathSecurityService(storage_path=store_file)
    sec.add_directory(str(temp_secure_dir["authorized"]))

    with patch("tools.filesystem.file_tools.get_path_security_service", return_value=sec):
        tool = FileSearchTextTool()
        ctx = ExecutionContext()

        res = tool.execute(
            FileSearchTextInput(
                directory_path=str(temp_secure_dir["authorized"]),
                query="Jarvis secure",
            ),
            ctx,
        )
        assert res.status.value == "success"
        assert res.data["match_count"] >= 1
        assert res.data["matches"][0]["file"] == "notes.txt"
