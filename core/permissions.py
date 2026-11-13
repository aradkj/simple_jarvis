"""Permission management and security enforcement interfaces for JARVIS."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PermissionCategory(StrEnum):
    """Classification of tool and action permission sensitivity."""

    READ_ONLY = "read_only"
    COMPUTATION = "computation"
    REVERSIBLE = "reversible"
    FILE_MODIFICATION = "file_modification"
    DESTRUCTIVE = "destructive"
    EXTERNAL_COMMUNICATION = "external_communication"
    SYSTEM_OPERATION = "system_operation"
    SYSTEM = "system_operation"
    SYSTEM_INFO = "system_info"
    NETWORK_INSPECT = "network_inspect"
    FILE_READ = "file_read"
    FILE_SEARCH = "file_search"
    WINDOWS_APP_READ = "windows_app_read"
    WINDOWS_APP_LAUNCH = "windows_app_launch"
    WINDOWS_APP_CLOSE = "windows_app_close"
    WINDOWS_WINDOW_READ = "windows_window_read"
    WINDOWS_WINDOW_CONTROL = "windows_window_control"
    WINDOWS_AUDIO_READ = "windows_audio_read"
    WINDOWS_AUDIO_CONTROL = "windows_audio_control"
    WINDOWS_DISPLAY_READ = "windows_display_read"
    WINDOWS_DISPLAY_CONTROL = "windows_display_control"
    WINDOWS_POWER_READ = "windows_power_read"
    WINDOWS_POWER_CONTROL = "windows_power_control"
    WINDOWS_OPERATION = "windows_operation"


class PermissionDecision(StrEnum):
    """Possible outcomes of a permission evaluation."""

    DENIED = "denied"
    GRANTED = "granted"
    REQUIRES_CONFIRMATION = "requires_confirmation"


@dataclass
class PermissionRequest:
    """Request object passed to the permission manager."""

    tool_name: str
    category: PermissionCategory
    action_summary: str
    target_resource: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionResult:
    """Result returned after evaluating a permission request."""

    decision: PermissionDecision
    category: PermissionCategory
    tool_name: str
    reason: str
    is_allowed: bool = False

    def __post_init__(self) -> None:
        self.is_allowed = self.decision == PermissionDecision.GRANTED


class BasePermissionManager:
    """Abstract interface for checking and enforcing tool permissions."""

    def evaluate(self, request: PermissionRequest) -> PermissionResult:
        """Evaluate a permission request and return a decision."""
        raise NotImplementedError

    def grant(self, category: PermissionCategory) -> None:
        """Explicitly allow a permission category."""
        raise NotImplementedError

    def revoke(self, category: PermissionCategory) -> None:
        """Revoke a previously granted permission category."""
        raise NotImplementedError

    def grant_proposal(self, proposal_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
        """Explicitly authorize a single exact proposal invocation (optional)."""
        pass

    def revoke_proposal(self, proposal_id: str) -> None:
        """Revoke a previously granted proposal authorization (optional)."""
        pass


class StrictDefaultDenyPermissionManager(BasePermissionManager):
    """Production-grade permission manager that defaults to denying all actions.

    Only explicitly whitelisted categories or tools are granted permission.
    """

    def __init__(self, allowed_categories: set[PermissionCategory] | None = None) -> None:
        # Default is strictly empty: everything is denied unless explicitly permitted
        self._allowed_categories: set[PermissionCategory] = (
            set(allowed_categories) if allowed_categories is not None else set()
        )
        self._allowed_tools: set[str] = set()
        self._approved_proposals: dict[str, tuple[str, str]] = {}

    def grant_proposal(self, proposal_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
        """Grant a single-use authorization for an exact proposal and parameter set."""
        clean_args = {k: v for k, v in arguments.items() if not str(k).startswith("_")}
        sig = f"{tool_name}:{sorted(clean_args.items())}"
        self._approved_proposals[proposal_id] = (tool_name, sig)

    def revoke_proposal(self, proposal_id: str) -> None:
        """Revoke a single-use proposal authorization."""
        self._approved_proposals.pop(proposal_id, None)

    def grant(self, category: PermissionCategory) -> None:
        """Allow an entire permission category."""
        self._allowed_categories.add(category)

    def revoke(self, category: PermissionCategory) -> None:
        """Revoke permission for a category."""
        self._allowed_categories.discard(category)

    def grant_tool(self, tool_name: str) -> None:
        """Allow a specific tool by name."""
        self._allowed_tools.add(tool_name)

    def revoke_tool(self, tool_name: str) -> None:
        """Revoke permission for a specific tool."""
        self._allowed_tools.discard(tool_name)

    def evaluate(self, request: PermissionRequest) -> PermissionResult:
        """Evaluate request using default-deny policy.

        If a single-use approved proposal matches exact tool & parameters, returns GRANTED.
        If the specific tool is explicitly allowed, returns GRANTED.
        If the category is explicitly allowed, returns GRANTED.
        Otherwise returns DENIED with a clear reason.
        """
        # 1. Single-use proposal authorization
        proposal_id = request.parameters.get("_proposal_id")
        if proposal_id and proposal_id in self._approved_proposals:
            expected_tool, expected_sig = self._approved_proposals[proposal_id]
            clean_args = {k: v for k, v in request.parameters.items() if not str(k).startswith("_")}
            actual_sig = f"{request.tool_name}:{sorted(clean_args.items())}"
            # Consume authorization regardless of match to enforce single-use
            self._approved_proposals.pop(proposal_id, None)
            if request.tool_name == expected_tool and actual_sig == expected_sig:
                return PermissionResult(
                    decision=PermissionDecision.GRANTED,
                    category=request.category,
                    tool_name=request.tool_name,
                    reason=f"Proposal '{proposal_id}' was explicitly authorized by user decision.",
                )
            else:
                return PermissionResult(
                    decision=PermissionDecision.DENIED,
                    category=request.category,
                    tool_name=request.tool_name,
                    reason=f"Proposal '{proposal_id}' execution denied: parameters or tool tampered after approval.",
                )

        # 2. Specific tool override
        if request.tool_name in self._allowed_tools:
            return PermissionResult(
                decision=PermissionDecision.GRANTED,
                category=request.category,
                tool_name=request.tool_name,
                reason=f"Tool '{request.tool_name}' is explicitly authorized.",
            )

        # 3. Category check
        if request.category in self._allowed_categories:
            return PermissionResult(
                decision=PermissionDecision.GRANTED,
                category=request.category,
                tool_name=request.tool_name,
                reason=f"Category '{request.category.value}' is authorized by current security policy.",
            )

        # 4. Default-deny
        return PermissionResult(
            decision=PermissionDecision.DENIED,
            category=request.category,
            tool_name=request.tool_name,
            reason=(
                f"Permission denied by default-deny security policy for category "
                f"'{request.category.value}' and tool '{request.tool_name}'."
            ),
        )
