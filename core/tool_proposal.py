"""Tool proposal models and security boundary validation for JARVIS Phase 3."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory

logger = logging.getLogger("jarvis.tool_proposal")

_DEFAULT_KEY_FILE = Path("data/.proposal_key")
_CACHED_SIGNING_KEY: bytes | None = None
_KEY_LOCK = threading.Lock()


def _restrict_file_permissions(file_path: Path) -> None:
    """Restrict access permissions to current owner, SYSTEM, and Administrators."""
    resolved = file_path.resolve()
    try:
        import stat

        os.chmod(resolved, stat.S_IRUSR | stat.S_IWUSR)
    except Exception as exc:
        logger.debug(f"chmod restriction warning on {resolved}: {exc}")

    if os.name == "nt":
        import subprocess

        user_domain = os.environ.get("USERDOMAIN", "")
        username = os.environ.get("USERNAME", "")
        user_spec = f"{user_domain}\\{username}" if user_domain and username else username
        if user_spec:
            cmd = [
                "icacls",
                str(resolved),
                "/inheritance:r",
                "/grant:r",
                f"{user_spec}:(F)",
                "/grant:r",
                "SYSTEM:(F)",
                "/grant:r",
                "Administrators:(F)",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                logger.warning(
                    f"icacls returned non-zero code {res.returncode}: {res.stderr or res.stdout}"
                )


def _atomic_write_key_file(target_file: Path, key_bytes: bytes) -> None:
    """Atomically write key material to disk with restricted permissions and fsync."""
    target_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = target_file.with_name(f"{target_file.name}.tmp.{secrets.token_hex(8)}")
    try:
        with open(temp_file, "wb") as f:
            f.write(key_bytes)
            f.flush()
            os.fsync(f.fileno())
        _restrict_file_permissions(temp_file)
        os.replace(temp_file, target_file)
        _restrict_file_permissions(target_file)
    finally:
        if temp_file.exists():
            with contextlib.suppress(Exception):
                temp_file.unlink()


def set_proposal_signing_key(key: bytes | None) -> None:
    """Explicitly set or reset the cached proposal signing key (for test isolation)."""
    global _CACHED_SIGNING_KEY
    with _KEY_LOCK:
        _CACHED_SIGNING_KEY = key


def reset_proposal_signing_key() -> None:
    """Reset the cached proposal signing key (for test isolation)."""
    set_proposal_signing_key(None)


def get_proposal_signing_key() -> bytes:
    """Retrieve or securely generate persistent HMAC signing key for proposals.

    Order of precedence:
    1. Explicit environment variable JARVIS_PROPOSAL_SECRET_KEY or JARVIS_SECRET_KEY (>= 32 bytes)
    2. Settings.proposal_signing_key if configured (>= 32 bytes)
    3. Persistent key in JARVIS_PROPOSAL_KEY_FILE or data/.proposal_key (>= 32 bytes)
    4. Cryptographically strong random 256-bit key (secrets.token_bytes(32)) generated and atomically persisted

    Fails closed if configured key is invalid, short, or cannot be secured.
    """
    global _CACHED_SIGNING_KEY
    with _KEY_LOCK:
        if _CACHED_SIGNING_KEY is not None:
            return _CACHED_SIGNING_KEY

        # 1. Environment variable inspection
        env_key = os.environ.get("JARVIS_PROPOSAL_SECRET_KEY") or os.environ.get(
            "JARVIS_SECRET_KEY"
        )
        if env_key is not None:
            raw_env = env_key.strip().encode("utf-8")
            if len(raw_env) < 32:
                raise ValueError(
                    "Configured environment proposal signing key must be at least 32 bytes (256 bits)."
                )
            _CACHED_SIGNING_KEY = raw_env
            return _CACHED_SIGNING_KEY

        # 2. Application settings inspection
        try:
            from config import get_settings

            settings = get_settings()
            if hasattr(settings, "proposal_signing_key") and settings.proposal_signing_key:
                val = settings.proposal_signing_key.get_secret_value()
                if val is not None and val.strip():
                    raw_cfg = val.strip().encode("utf-8")
                    if len(raw_cfg) < 32:
                        raise ValueError(
                            "Configured Settings.proposal_signing_key must be at least 32 bytes (256 bits)."
                        )
                    _CACHED_SIGNING_KEY = raw_cfg
                    return _CACHED_SIGNING_KEY
        except ValueError:
            raise
        except Exception:
            pass

        # 3. Persistent key file inspection
        key_file_path = Path(os.environ.get("JARVIS_PROPOSAL_KEY_FILE", "data/.proposal_key"))
        if key_file_path.exists():
            key_bytes = key_file_path.read_bytes()
            if len(key_bytes) > 32 and key_bytes.endswith((b"\r", b"\n")):
                key_bytes = key_bytes.rstrip(b"\r\n")
            if len(key_bytes) < 32:
                raise ValueError(
                    f"Proposal signing key file '{key_file_path}' contains invalid or truncated key material "
                    f"({len(key_bytes)} bytes < 32 bytes). Refusing to proceed with insecure key."
                )
            _CACHED_SIGNING_KEY = key_bytes
            return _CACHED_SIGNING_KEY

        # 4. Generate fresh 256-bit cryptographic key atomically
        new_key = secrets.token_bytes(32)
        try:
            _atomic_write_key_file(key_file_path, new_key)
        except Exception as exc:
            raise RuntimeError(f"Failed to atomically persist proposal signing key: {exc}") from exc

        _CACHED_SIGNING_KEY = new_key
        return _CACHED_SIGNING_KEY


def _canonical_json(data: Any) -> str:
    """Deterministic, canonical JSON serialization without whitespace variations.

    Ensures:
    - Dict keys are sorted and must be strings.
    - No whitespace between tokens (separators=(',', ':')).
    - UTF-8 ensure_ascii=False.
    - allow_nan=False (NaN and Infinity raise ValueError, failing closed).
    - Unsupported types fail closed (raise TypeError).
    """

    def _validate_keys(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if not isinstance(k, str):
                    raise ValueError(
                        f"Dictionary keys must be strings for canonical serialization, got {type(k).__name__}"
                    )
                _validate_keys(v)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _validate_keys(item)

    _validate_keys(data)
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


class RiskLevel(StrEnum):
    """Risk classification for tool proposals."""

    LOW = "low"  # Read-only information retrieval, math, format parsing
    MEDIUM = "medium"  # State queries, non-destructive status checks
    HIGH = "high"  # Modifying session state, simulated sensitive operations
    CRITICAL = "critical"  # Destructive, system-level, or unvetted actions


class ProposalStatus(StrEnum):
    """Lifecycle status of a proposed tool invocation."""

    CREATED = "created"
    PROPOSED = "proposed"  # Compatibility alias for CREATED
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class ToolProposal:
    """Represents a proposed tool invocation before authorization or execution."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    target_identity: str = ""
    status: ProposalStatus = ProposalStatus.PROPOSED
    rationale: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    approved_signature: str | None = None
    executed_at: datetime | None = None
    result: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._consumed = False
        if isinstance(self.arguments, dict):
            import copy

            self.arguments = copy.deepcopy(self.arguments)
        if not self.target_identity and isinstance(self.arguments, dict):
            self.target_identity = str(
                self.arguments.get("file_path")
                or self.arguments.get("path")
                or self.arguments.get("target")
                or self.arguments.get("url")
                or ""
            )

    def _resolve_key(self, key: bytes | str | None) -> bytes:
        if key is not None:
            k_bytes = key.encode("utf-8") if isinstance(key, str) else bytes(key)
            if len(k_bytes) < 32:
                raise ValueError(
                    "HMAC signing key must be at least 32 bytes (256 bits) for cryptographic security"
                )
            return k_bytes
        return get_proposal_signing_key()

    def compute_signature(self, key: bytes | str | None = None) -> str:
        """Generate genuine HMAC-SHA256 signature binding complete execution payload."""
        signing_key = self._resolve_key(key)
        tgt = self.target_identity or (
            str(
                self.arguments.get("file_path")
                or self.arguments.get("path")
                or self.arguments.get("target")
                or self.arguments.get("url")
                or ""
            )
            if isinstance(self.arguments, dict)
            else ""
        )
        payload = {
            "v": 1,
            "proposal_id": self.proposal_id,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "target_identity": tgt,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
        canonical_bytes = _canonical_json(payload).encode("utf-8")
        mac = hmac.new(signing_key, canonical_bytes, hashlib.sha256).hexdigest()
        return f"v1:{mac}"

    def approve(
        self, key: bytes | str | None = None, expires_in_seconds: float | None = None
    ) -> None:
        """Authorize the proposal for bounded execution using HMAC signature."""
        with getattr(self, "_lock", threading.RLock()):
            if self.status in (
                ProposalStatus.REJECTED,
                ProposalStatus.CANCELLED,
                ProposalStatus.EXPIRED,
                ProposalStatus.EXECUTING,
                ProposalStatus.EXECUTED,
                ProposalStatus.FAILED,
            ):
                raise ValueError(
                    f"Cannot approve proposal in terminal status '{self.status.value}'"
                )
            if self.status == ProposalStatus.APPROVED:
                raise ValueError(
                    "Proposal is already approved; cannot re-approve or regenerate authorization"
                )
            if self.status not in (
                ProposalStatus.PROPOSED,
                ProposalStatus.CREATED,
                ProposalStatus.PENDING_APPROVAL,
            ):
                raise ValueError(
                    f"Invalid proposal state transition to APPROVED from '{self.status.value}'"
                )

            self.status = ProposalStatus.APPROVED
            self.approved_at = datetime.now(UTC)
            if expires_in_seconds is not None and expires_in_seconds > 0:
                self.expires_at = self.approved_at + timedelta(seconds=expires_in_seconds)
            self.approved_signature = self.compute_signature(key=key)

    def reject(self, reason: str = "User or policy rejected execution") -> None:
        """Deny authorization for the proposal."""
        with getattr(self, "_lock", threading.RLock()):
            if self.status in (ProposalStatus.EXECUTED, ProposalStatus.FAILED):
                raise ValueError(f"Cannot reject proposal in terminal status '{self.status.value}'")
            self.status = ProposalStatus.REJECTED
            self.error = reason
            self.approved_signature = None

    def expire(self, reason: str = "Approval request timed out") -> None:
        """Mark proposal as expired due to timeout."""
        with getattr(self, "_lock", threading.RLock()):
            if self.status in (ProposalStatus.EXECUTED, ProposalStatus.FAILED):
                raise ValueError(f"Cannot expire proposal in terminal status '{self.status.value}'")
            self.status = ProposalStatus.EXPIRED
            self.error = reason
            self.approved_signature = None

    def cancel(self, reason: str = "Execution cancelled") -> None:
        """Cancel the in-flight proposal."""
        with getattr(self, "_lock", threading.RLock()):
            if self.status in (ProposalStatus.EXECUTED, ProposalStatus.FAILED):
                raise ValueError(f"Cannot cancel proposal in terminal status '{self.status.value}'")
            self.status = ProposalStatus.CANCELLED
            self.error = reason
            self.approved_signature = None

    def is_valid_approval(self, key: bytes | str | None = None) -> bool:
        """Verify proposal is approved and parameters have not been tampered with."""
        with getattr(self, "_lock", threading.RLock()):
            if self.status != ProposalStatus.APPROVED:
                return False
            if not self.approved_signature:
                return False
            if self.expires_at is not None:
                try:
                    exp = self.expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=UTC)
                    if datetime.now(UTC) > exp:
                        return False
                except Exception:
                    return False
            if self.approved_at is not None:
                try:
                    app = self.approved_at
                    if app.tzinfo is None:
                        app = app.replace(tzinfo=UTC)
                    now_utc = datetime.now(UTC)
                    if app > now_utc + timedelta(seconds=60):
                        return False
                    if now_utc - app > timedelta(hours=24):
                        return False
                except Exception:
                    return False
            try:
                expected_sig = self.compute_signature(key=key)
                return hmac.compare_digest(self.approved_signature, expected_sig)
            except Exception:
                return False

    def consume_for_execution(self, key: bytes | str | None = None) -> bool:
        """Atomically verify and consume the proposal authorization for single execution.

        Transitions state from APPROVED to EXECUTING.
        Returns False if not validly approved, already consumed, expired, or tampered.
        """
        with getattr(self, "_lock", threading.RLock()):
            if getattr(self, "_consumed", False):
                return False
            if not self.is_valid_approval(key=key):
                return False
            self._consumed = True
            self.status = ProposalStatus.EXECUTING
            return True

    def mark_executed(self, result: Any) -> None:
        """Record successful execution result."""
        with getattr(self, "_lock", threading.RLock()):
            if self.status not in (
                ProposalStatus.EXECUTING,
                ProposalStatus.APPROVED,
                ProposalStatus.PROPOSED,
            ):
                raise ValueError(
                    f"Cannot mark executed from terminal or invalid status '{self.status.value}'"
                )
            self.status = ProposalStatus.EXECUTED
            self.result = result
            self.executed_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        """Record execution failure."""
        with getattr(self, "_lock", threading.RLock()):
            if self.status == ProposalStatus.EXECUTED:
                raise ValueError("Cannot mark an already executed proposal as failed")
            self.status = ProposalStatus.FAILED
            self.error = error
            self.executed_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Convert proposal attributes to serializable dictionary."""
        return {
            "proposal_id": self.proposal_id,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "target_identity": self.target_identity,
            "status": self.status.value,
            "rationale": self.rationale,
            "created_at": self.created_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "approved_signature": self.approved_signature,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "error": self.error,
        }


class ToolDefinition(BaseModel):
    """Metadata schema defining a tool available to the planner."""

    name: str
    description: str
    category: PermissionCategory = PermissionCategory.SYSTEM
    risk_level: RiskLevel = RiskLevel.LOW
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False

    def to_openai_function_declaration(self) -> dict[str, Any]:
        """Format definition into standard OpenAI / Responses API function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema or {"type": "object", "properties": {}},
            },
        }

    def to_gemini_declaration(self) -> dict[str, Any]:
        """Format definition into Gemini function declaration schema."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema or {"type": "object", "properties": {}},
        }
