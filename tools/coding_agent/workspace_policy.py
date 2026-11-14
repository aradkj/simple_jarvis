"""Workspace Policy Validator and Least-Privilege Enforcer for Antigravity Coding Agent Subsystem."""

from __future__ import annotations

import re
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
    "syswow64",
    "program files",
    "program files (x86)",
    "programdata",
}

FORBIDDEN_DIR_NAMES = {
    ".ssh",
    ".aws",
    ".gemini",
    ".azure",
    "credentials",
}

FORBIDDEN_FILE_PATTERNS = [
    re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE),
    re.compile(r"^.*\.pem$", re.IGNORECASE),
    re.compile(r"^.*\.key$", re.IGNORECASE),
    re.compile(r"^id_rsa.*$", re.IGNORECASE),
    re.compile(r"^.*\.sqlite[3]?$", re.IGNORECASE),
    re.compile(r"^tasks\.db$", re.IGNORECASE),
    re.compile(r"^memory\.db$", re.IGNORECASE),
    re.compile(r"^.*config$", re.IGNORECASE),  # .git/config
]

DISALLOWED_COMMAND_TOKENS = [
    "runas",
    "start-process -verb runas",
    "sudo",
    "uac",
    "format",
    "diskpart",
    "bcdedit",
    "net user",
    "reg delete",
    "invoke-expression",
    "iex ",
    "downloadstring",
    "certutil",
    "powershell -enc",
    "powershell -encodedcommand",
    "--dangerously-skip-permissions",
]

APPROVED_COMMAND_PREFIXES = [
    "git ",
    "git.exe ",
    "pytest",
    "python -m pytest",
    "python.exe -m pytest",
    "python -m unittest",
    "python.exe -m unittest",
    "ruff check",
    "ruff format",
    "npm test",
    "npm run ",
    "cargo test",
    "cargo check",
    "cargo build",
    "go test",
    "go build",
]


class WorkspacePolicy:
    """Validates workspaces, commands, and file diffs against least-privilege security policy."""

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
        for part in resolved.parts[1:4]:
            if part.lower() in SYSTEM_DIRECTORIES and "jarvis" not in str(resolved).lower():
                raise WorkspacePolicyViolationError(
                    f"System directory cannot be an authorized coding workspace: '{resolved}'"
                )

        # Disallow sensitive user credential directories
        for part in resolved.parts:
            if part.lower() in FORBIDDEN_DIR_NAMES:
                raise WorkspacePolicyViolationError(
                    f"Sensitive user directory '{part}' cannot be an authorized coding workspace."
                )

        # Disallow targeting JARVIS internal private data directory
        jarvis_data = (Path.cwd() / "data").resolve()
        try:
            resolved.relative_to(jarvis_data)
            raise WorkspacePolicyViolationError(
                "Access denied: JARVIS internal database directory cannot be an Antigravity workspace."
            )
        except ValueError:
            pass

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

    @classmethod
    def validate_file_access(cls, workspace: Path, file_path: str | Path) -> Path:
        """Validate that target file is contained strictly inside workspace and not a forbidden secret."""
        resolved_ws = workspace.resolve()
        target = Path(file_path)
        target = (resolved_ws / target).resolve() if not target.is_absolute() else target.resolve()

        # Traversal containment check
        try:
            target.relative_to(resolved_ws)
        except ValueError as err:
            raise WorkspacePolicyViolationError(
                f"Path traversal violation: '{target}' is outside workspace '{resolved_ws}'."
            ) from err

        # Symlink / reparse point check
        if is_reparse_point(target):
            raise WorkspacePolicyViolationError(
                f"Reparse points and symlinks are prohibited: '{target}'."
            )

        # Forbidden secret file patterns
        fname = target.name.lower()
        for pat in FORBIDDEN_FILE_PATTERNS:
            if pat.match(fname):
                raise WorkspacePolicyViolationError(
                    f"Access denied to sensitive secret/database file: '{fname}'."
                )

        return target

    @classmethod
    def validate_command_string(cls, command_str: str) -> None:
        """Evaluate command string according to least-privilege policy.

        Rejects wildcard commands, privilege escalation, destructive commands,
        and unapproved execution vectors.
        """
        cmd_clean = command_str.strip().lower()
        if not cmd_clean:
            raise WorkspacePolicyViolationError("Empty command string is not allowed.")

        # Disallow wildcard
        if cmd_clean == "*" or cmd_clean.startswith("command(*)"):
            raise WorkspacePolicyViolationError(
                "Wildcard command execution 'command(*)' is strictly prohibited."
            )

        # Check disallowed tokens
        for token in DISALLOWED_COMMAND_TOKENS:
            if token in cmd_clean:
                raise WorkspacePolicyViolationError(
                    f"Command contains prohibited security token '{token}': '{command_str}'."
                )

        # Check approved prefixes
        matched = False
        for prefix in APPROVED_COMMAND_PREFIXES:
            if cmd_clean.startswith(prefix) or cmd_clean == prefix.strip():
                matched = True
                break

        if not matched:
            raise WorkspacePolicyViolationError(
                f"Command '{command_str}' is not in the approved development operations whitelist."
            )

    @classmethod
    def validate_modified_files(cls, workspace: Path, changed_files: list[str]) -> list[str]:
        """Inspect all modified files in git diff and verify none violate security policy."""
        resolved_ws = workspace.resolve()
        validated: list[str] = []

        for rel_path in changed_files:
            clean_rel = rel_path.strip().lstrip("? ").strip()
            if not clean_rel:
                continue

            full_path = (resolved_ws / clean_rel).resolve()

            # Containment check
            try:
                full_path.relative_to(resolved_ws)
            except ValueError as err:
                raise WorkspacePolicyViolationError(
                    f"Security violation: Modified file '{clean_rel}' lies outside workspace root."
                ) from err

            # Symlink check
            if is_reparse_point(full_path):
                raise WorkspacePolicyViolationError(
                    f"Security violation: Modified file '{clean_rel}' is a prohibited reparse point."
                )

            # Forbidden file names (.env, credentials, tasks.db, etc.)
            fname = full_path.name.lower()
            for pat in FORBIDDEN_FILE_PATTERNS:
                if pat.match(fname):
                    raise WorkspacePolicyViolationError(
                        f"Security violation: Modification of sensitive file '{clean_rel}' is strictly prohibited."
                    )

            validated.append(clean_rel)

        return validated
