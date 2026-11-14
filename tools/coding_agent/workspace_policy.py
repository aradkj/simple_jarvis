"""Workspace Policy Validator for Antigravity Coding Agent Subsystem."""

from __future__ import annotations

import tempfile
from pathlib import Path

from config import get_settings
from infrastructure.logging import get_logger
from tools.coding_agent.exceptions import WorkspacePolicyViolationError
from tools.filesystem.path_security import is_reparse_point

logger = get_logger("workspace_policy")

SYSTEM_DIRECTORIES = {
    "windows",
    "system32",
    "program files",
    "program files (x86)",
    "programdata",
}


class WorkspacePolicy:
    """Validates workspaces before allowing code generation or terminal modifications."""

    @classmethod
    def validate_workspace(cls, workspace_path: str | Path) -> Path:
        """Strictly validate workspace directory against security boundaries."""
        settings = get_settings()
        raw_p = Path(workspace_path)

        # Reject null bytes and alternate data streams
        if "\x00" in str(workspace_path) or ":" in raw_p.name:
            raise WorkspacePolicyViolationError("Invalid workspace path syntax.")

        try:
            resolved = raw_p.resolve()
        except Exception as exc:
            raise WorkspacePolicyViolationError(f"Malformed workspace path: {exc}") from exc

        if not resolved.exists():
            raise WorkspacePolicyViolationError(f"Workspace path does not exist: '{resolved}'")
        if not resolved.is_dir():
            raise WorkspacePolicyViolationError(f"Workspace path must be a directory: '{resolved}'")

        # Disallow root drive as workspace (e.g., C:\)
        if resolved == resolved.parent or len(resolved.parts) <= 1:
            raise WorkspacePolicyViolationError(
                f"Root drive cannot be an authorized coding workspace: '{resolved}'"
            )

        # Disallow Windows system directories
        for part in resolved.parts[1:3]:  # Check immediate top-level directories
            if part.lower() in SYSTEM_DIRECTORIES and "jarvis" not in str(resolved).lower():
                raise WorkspacePolicyViolationError(
                    f"System directory cannot be an authorized coding workspace: '{resolved}'"
                )

        # Disallow reparse points (symlinks/junctions)
        if is_reparse_point(resolved):
            raise WorkspacePolicyViolationError(
                f"Reparse points and directory junctions are prohibited: '{resolved}'"
            )

        # Check against authorized workspaces if configured
        allowed_workspaces = [Path(w).resolve() for w in settings.antigravity_authorized_workspaces]
        current_project_root = Path.cwd().resolve()
        allowed_workspaces.append(current_project_root)
        allowed_workspaces.append(Path(tempfile.gettempdir()).resolve())

        contained = False
        for auth_ws in allowed_workspaces:
            try:
                resolved.relative_to(auth_ws)
                contained = True
                break
            except ValueError:
                continue

        if not contained:
            raise WorkspacePolicyViolationError(
                f"Workspace '{resolved}' is not inside an authorized development directory."
            )

        return resolved
