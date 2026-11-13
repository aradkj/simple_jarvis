"""Unit tests for permission manager and default-deny security enforcement."""

from core.permissions import (
    PermissionCategory,
    PermissionDecision,
    PermissionRequest,
    StrictDefaultDenyPermissionManager,
)


def test_strict_default_deny_all_categories() -> None:
    """Verify that every single permission category defaults to DENIED."""
    manager = StrictDefaultDenyPermissionManager()

    for category in PermissionCategory:
        request = PermissionRequest(
            tool_name="test_tool",
            category=category,
            action_summary="Test action",
        )
        result = manager.evaluate(request)
        assert result.decision == PermissionDecision.DENIED
        assert result.is_allowed is False
        assert "default-deny" in result.reason.lower()


def test_grant_and_revoke_category() -> None:
    """Verify granting a category allows actions in that category, and revoking restores denial."""
    manager = StrictDefaultDenyPermissionManager()

    request = PermissionRequest(
        tool_name="reader_tool",
        category=PermissionCategory.READ_ONLY,
        action_summary="Read data",
    )

    # Initially denied
    assert manager.evaluate(request).decision == PermissionDecision.DENIED

    # Grant category
    manager.grant(PermissionCategory.READ_ONLY)
    granted_result = manager.evaluate(request)
    assert granted_result.decision == PermissionDecision.GRANTED
    assert granted_result.is_allowed is True

    # Other categories must still be denied
    destructive_request = PermissionRequest(
        tool_name="delete_tool",
        category=PermissionCategory.DESTRUCTIVE,
        action_summary="Delete files",
    )
    assert manager.evaluate(destructive_request).decision == PermissionDecision.DENIED

    # Revoke category
    manager.revoke(PermissionCategory.READ_ONLY)
    assert manager.evaluate(request).decision == PermissionDecision.DENIED


def test_grant_and_revoke_specific_tool() -> None:
    """Verify explicitly authorizing a specific tool allows it without opening entire category."""
    manager = StrictDefaultDenyPermissionManager()

    tool_req = PermissionRequest(
        tool_name="special_backup_tool",
        category=PermissionCategory.FILE_MODIFICATION,
        action_summary="Backup file",
    )
    other_req = PermissionRequest(
        tool_name="arbitrary_file_tool",
        category=PermissionCategory.FILE_MODIFICATION,
        action_summary="Modify system file",
    )

    # Initially both denied
    assert manager.evaluate(tool_req).decision == PermissionDecision.DENIED
    assert manager.evaluate(other_req).decision == PermissionDecision.DENIED

    # Authorize specific tool
    manager.grant_tool("special_backup_tool")
    assert manager.evaluate(tool_req).decision == PermissionDecision.GRANTED
    assert manager.evaluate(other_req).decision == PermissionDecision.DENIED

    # Revoke tool
    manager.revoke_tool("special_backup_tool")
    assert manager.evaluate(tool_req).decision == PermissionDecision.DENIED
