"""End-to-End Human Approval Lifecycle Manager for JARVIS Phase 3.

Provides thread-safe coordination between background agent execution threads
and the UI main thread for high-risk / critical tool proposal authorizations.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from core.events import AgentEvent, AgentEventType, EventBus
from core.execution_context import CancellationToken
from core.permissions import BasePermissionManager
from core.tool_proposal import ProposalStatus, ToolProposal
from infrastructure.logging import get_logger

logger = get_logger("approval")


@dataclass
class ApprovedRecord:
    proposal_id: str
    tool_name: str
    account_id: str
    recipient: str
    payload_hash: str
    approved_at: float
    consumed: bool = False
    consumed_at: float | None = None
    session_id: str = ""


class TrustedApprovalStore:
    """Independent, trusted storage for cryptographic approval digests.

    Guarantees:
    - Binds exact account, operation, recipient, message content, attachments.
    - Prevents payload replacement and hash replacement attacks.
    - Invalidates approval if any payload content or attachment bytes are modified.
    - Prevents replay of already-consumed approvals.
    - Independently verifies email and WhatsApp dispatch paths.
    """

    _instance: TrustedApprovalStore | None = None

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, ApprovedRecord] = {}
        self._hash_to_proposal: dict[str, str] = {}

    @classmethod
    def get_instance(cls) -> TrustedApprovalStore:
        if cls._instance is None:
            cls._instance = TrustedApprovalStore()
        return cls._instance

    def register_approval(
        self,
        proposal_id: str,
        tool_name: str,
        account_id: str,
        recipient: str,
        payload_hash: str,
        session_id: str = "",
    ) -> ApprovedRecord:
        """Store approved payload digest in trusted independent storage."""
        with self._lock:
            record = ApprovedRecord(
                proposal_id=proposal_id,
                tool_name=tool_name,
                account_id=account_id.strip().lower(),
                recipient=recipient.strip(),
                payload_hash=payload_hash.strip().lower(),
                approved_at=time.time(),
                consumed=False,
                session_id=session_id,
            )
            self._records[proposal_id] = record
            self._hash_to_proposal[record.payload_hash] = proposal_id
            logger.info(
                f"TrustedApprovalStore registered approval for {tool_name} "
                f"(proposal={proposal_id}, account={account_id}, hash={payload_hash[:12]}...)"
            )
            return record

    def has_approval(self, payload_hash: str) -> bool:
        """Check whether an approval record exists for the given hash."""
        with self._lock:
            return payload_hash.strip().lower() in self._hash_to_proposal

    def verify_and_consume(
        self,
        tool_name: str,
        account_id: str,
        recipient: str,
        actual_payload_hash: str,
        proposal_id: str | None = None,
    ) -> tuple[bool, str]:
        """Verify the payload against an independently recorded approval and mark it consumed."""
        with self._lock:
            record: ApprovedRecord | None = None
            if proposal_id and proposal_id in self._records:
                record = self._records[proposal_id]
            elif actual_payload_hash.strip().lower() in self._hash_to_proposal:
                pid = self._hash_to_proposal[actual_payload_hash.strip().lower()]
                record = self._records.get(pid)

            if not record:
                return (
                    False,
                    "No trusted approval record found for this operation. Explicit approval required.",
                )

            # 1. Replay check
            if record.consumed:
                return (
                    False,
                    f"Approval for proposal '{record.proposal_id}' has already been consumed (replay blocked).",
                )

            # 2. Tool name verification
            if record.tool_name != tool_name:
                return (
                    False,
                    f"Tool mismatch: approval is for '{record.tool_name}', attempted '{tool_name}'.",
                )

            # 3. Account ID binding check (prevents account substitution)
            if record.account_id and account_id and record.account_id != account_id.strip().lower():
                return (
                    False,
                    f"Account substitution detected: approval was granted for '{record.account_id}', but attempted '{account_id}'.",
                )

            # 4. Recipient binding check (prevents recipient substitution)
            if record.recipient and recipient and record.recipient != recipient.strip():
                return (
                    False,
                    f"Recipient substitution detected: approval was granted for '{record.recipient}', but attempted '{recipient}'.",
                )

            # 5. Payload hash tampering check (invalidates approval if content or attachments changed)
            if record.payload_hash != actual_payload_hash.strip().lower():
                return (
                    False,
                    "Payload tampering detected: payload contents or attachments were modified after approval.",
                )

            # Mark approval consumed immediately before dispatch
            record.consumed = True
            record.consumed_at = time.time()
            logger.info(
                f"TrustedApprovalStore consumed approval for {tool_name} (proposal={record.proposal_id})"
            )
            return True, ""

    def clear(self) -> None:
        """Clear all stored approval records."""
        with self._lock:
            self._records.clear()
            self._hash_to_proposal.clear()


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
                    if proposal.status != ProposalStatus.APPROVED:
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
                    if proposal.status != ProposalStatus.REJECTED:
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
        source: str = "ui",
    ) -> bool:
        """Submit a user approval or rejection decision.

        Validations enforced:
        - Proposal must be currently pending.
        - Session ID must match the proposal's session ID.
        - Replay, duplicate, or stale decisions are rejected.
        - Voice recognition alone cannot approve high-risk outbound communication (email_send / whatsapp_send).

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

            # Voice approval safety check: Voice recognition alone cannot approve external dispatches
            if approved and source.lower() == "voice":
                from core.permissions import PermissionCategory

                cat = getattr(proposal, "category", None)
                if cat in (
                    PermissionCategory.EMAIL_SEND,
                    PermissionCategory.WHATSAPP_SEND,
                ) or proposal.tool_name in ("email_send", "whatsapp_send"):
                    logger.warning(
                        f"Voice approval rejected for proposal '{proposal_id}' ({proposal.tool_name}): "
                        "External sends require explicit manual UI approval for safety."
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
