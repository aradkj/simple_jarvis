"""End-to-End Human Approval Lifecycle Manager for JARVIS Phase 3.

Provides thread-safe coordination between background agent execution threads
and the UI main thread for high-risk / critical tool proposal authorizations.
"""

from __future__ import annotations

import threading
import time

from core.events import AgentEvent, AgentEventType, EventBus
from core.execution_context import CancellationToken
from core.permissions import BasePermissionManager
from core.tool_proposal import ProposalStatus, ToolProposal
from infrastructure.logging import get_logger

logger = get_logger("approval")


class ApprovalManager:
    """Coordinates tool execution proposals and human approval decisions.

    Guarantees:
    - Default-deny: Missing, expired, or rejected responses never execute.
    - Session-bound: Approvals from other sessions are rejected.
    - Proposal-bound: An approval applies only to the exact proposal ID and arguments.
    - Tamper-proof: Modifying arguments or tool name after approval invalidates it.
    - Non-blocking to GUI: Background thread waits on a threading.Event, GUI remains 100% interactive.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        permission_manager: BasePermissionManager | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.event_bus = event_bus
        self.permission_manager = permission_manager

        # proposal_id -> ToolProposal
        self._pending_proposals: dict[str, ToolProposal] = {}
        # proposal_id -> threading.Event
        self._decision_events: dict[str, threading.Event] = {}
        # proposal_id -> (approved: bool, reason: str)
        self._decisions: dict[str, tuple[bool, str]] = {}
        # proposal_id -> initial signature
        self._initial_signatures: dict[str, str] = {}

    def request_approval(
        self,
        proposal: ToolProposal,
        timeout: float | None = 60.0,
        cancellation_token: CancellationToken | None = None,
    ) -> bool:
        """Wait synchronously on background thread for user approval decision.

        Returns:
            True if user explicitly approved the exact proposal, False otherwise.
        """
        # 1. Immediate cancellation check
        if cancellation_token and cancellation_token.is_cancelled():
            proposal.cancel("Cancelled before approval requested.")
            return False

        proposal_id = proposal.proposal_id
        event = threading.Event()
        initial_sig = proposal.compute_signature()

        with self._lock:
            proposal.status = ProposalStatus.PENDING_APPROVAL
            self._pending_proposals[proposal_id] = proposal
            self._decision_events[proposal_id] = event
            self._initial_signatures[proposal_id] = initial_sig

        logger.info(
            f"Approval requested for proposal '{proposal_id}' (tool='{proposal.tool_name}', "
            f"risk='{proposal.risk_level.value}', session='{proposal.session_id}')"
        )

        if self.event_bus:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.APPROVAL_REQUIRED,
                    payload=proposal.to_dict(),
                )
            )

        start_time = time.perf_counter()
        wait_interval = 0.05

        try:
            while not event.is_set():
                # Check cancellation
                if cancellation_token and cancellation_token.is_cancelled():
                    with self._lock:
                        proposal.cancel("Execution cancelled while waiting for user approval.")
                    if self.event_bus:
                        self.event_bus.publish(
                            AgentEvent(
                                event_type=AgentEventType.APPROVAL_REJECTED,
                                payload={"proposal_id": proposal_id, "reason": "Cancelled by user"},
                            )
                        )
                    return False

                # Check timeout
                if timeout and timeout > 0:
                    elapsed = time.perf_counter() - start_time
                    if elapsed >= timeout:
                        with self._lock:
                            proposal.expire(f"Approval request timed out after {timeout}s.")
                        logger.warning(f"Proposal '{proposal_id}' expired due to timeout.")
                        if self.event_bus:
                            self.event_bus.publish(
                                AgentEvent(
                                    event_type=AgentEventType.APPROVAL_REJECTED,
                                    payload={"proposal_id": proposal_id, "reason": "Timed out"},
                                )
                            )
                        return False

                event.wait(wait_interval)

            # Decision received
            with self._lock:
                approved, reason = self._decisions.get(proposal_id, (False, "No decision recorded"))

                # Tamper check: Ensure tool name and arguments were not modified
                current_sig = proposal.compute_signature()
                if current_sig != initial_sig:
                    proposal.reject("Proposal parameters were tampered with after request.")
                    logger.error(f"Proposal '{proposal_id}' rejected due to signature mismatch.")
                    return False

                if approved:
                    proposal.approve()
                    if self.permission_manager and hasattr(
                        self.permission_manager, "grant_proposal"
                    ):
                        self.permission_manager.grant_proposal(
                            proposal_id=proposal_id,
                            tool_name=proposal.tool_name,
                            arguments=proposal.arguments,
                        )
                    logger.info(f"Proposal '{proposal_id}' approved for single execution.")
                    if self.event_bus:
                        self.event_bus.publish(
                            AgentEvent(
                                event_type=AgentEventType.APPROVAL_GRANTED,
                                payload={
                                    "proposal_id": proposal_id,
                                    "tool_name": proposal.tool_name,
                                },
                            )
                        )
                    return True
                else:
                    proposal.reject(reason or "User rejected tool proposal.")
                    logger.info(f"Proposal '{proposal_id}' rejected: {reason}")
                    if self.event_bus:
                        self.event_bus.publish(
                            AgentEvent(
                                event_type=AgentEventType.APPROVAL_REJECTED,
                                payload={"proposal_id": proposal_id, "reason": reason},
                            )
                        )
                    return False

        finally:
            with self._lock:
                self._pending_proposals.pop(proposal_id, None)
                self._decision_events.pop(proposal_id, None)
                self._decisions.pop(proposal_id, None)
                self._initial_signatures.pop(proposal_id, None)

    def submit_decision(
        self,
        proposal_id: str,
        approved: bool,
        session_id: str,
        reason: str = "",
    ) -> bool:
        """Submit a user approval or rejection decision.

        Validations enforced:
        - Proposal must be currently pending.
        - Session ID must match the proposal's session ID.
        - Replay, duplicate, or stale decisions are rejected.

        Returns:
            True if the decision was successfully delivered, False otherwise.
        """
        with self._lock:
            proposal = self._pending_proposals.get(proposal_id)
            if not proposal:
                logger.warning(f"Rejected decision: proposal '{proposal_id}' is not pending.")
                return False

            # Session binding check
            if proposal.session_id and proposal.session_id != session_id:
                logger.warning(
                    f"Rejected decision: proposal '{proposal_id}' belongs to session "
                    f"'{proposal.session_id}', not '{session_id}'."
                )
                return False

            # Status check: only pending proposals may be decided
            if proposal.status != ProposalStatus.PENDING_APPROVAL:
                logger.warning(
                    f"Rejected decision: proposal '{proposal_id}' is in status '{proposal.status.value}'."
                )
                return False

            # Check if event exists
            event = self._decision_events.get(proposal_id)
            if not event:
                logger.warning(
                    f"Rejected decision: no waiting thread for proposal '{proposal_id}'."
                )
                return False

            # Record decision and wake waiting execution thread
            self._decisions[proposal_id] = (approved, reason)
            if approved:
                proposal.approve()
            else:
                proposal.reject(reason or "User rejected tool proposal.")
            event.set()
            logger.info(
                f"Recorded decision for proposal '{proposal_id}': "
                f"{'APPROVED' if approved else 'REJECTED'} (session='{session_id}')"
            )
            return True

    def cancel_session(self, session_id: str, reason: str = "Session cancelled") -> None:
        """Cancel all pending proposals for a specific session."""
        with self._lock:
            to_cancel = [
                pid
                for pid, prop in self._pending_proposals.items()
                if prop.session_id == session_id
            ]
            for pid in to_cancel:
                prop = self._pending_proposals[pid]
                prop.cancel(reason)
                self._decisions[pid] = (False, reason)
                evt = self._decision_events.get(pid)
                if evt:
                    evt.set()

    def get_pending_proposal(self, session_id: str | None = None) -> ToolProposal | None:
        """Retrieve the currently active pending proposal, optionally filtering by session."""
        with self._lock:
            for prop in self._pending_proposals.values():
                if prop.status == ProposalStatus.PENDING_APPROVAL and (
                    session_id is None or prop.session_id == session_id
                ):
                    return prop
            return None

    def clear(self) -> None:
        """Clear all pending state and wake all waiting threads."""
        with self._lock:
            for pid, evt in self._decision_events.items():
                self._decisions[pid] = (False, "Manager shutdown")
                evt.set()
            self._pending_proposals.clear()
            self._decision_events.clear()
            self._decisions.clear()
            self._initial_signatures.clear()
