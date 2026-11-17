"""Deterministic agent state machine for JARVIS Phase 3."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.events import AgentEvent, AgentEventType, EventBus
from infrastructure.logging import get_logger

logger = get_logger("state_machine")


class AgentState(StrEnum):
    """Operational states of the JARVIS agent orchestrator."""

    IDLE = "idle"
    ANALYZING = "analyzing"
    UNDERSTANDING = "understanding"
    CONTEXT_RETRIEVAL = "context_retrieval"
    ENVIRONMENT_DISCOVERY = "environment_discovery"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    # Backward compatibility with Phase 1 / Phase 2
    INITIALIZING = "idle"
    BUSY = "executing"
    ERROR = "failed"
    SHUTDOWN = "cancelled"


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, from_state: AgentState, to_state: AgentState, reason: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        msg = f"Cannot transition from {from_state.value} to {to_state.value}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


@dataclass
class StateTransitionRecord:
    """Historical record of an agent state change."""

    from_state: AgentState
    to_state: AgentState
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentStateMachine:
    """Thread-safe, deterministic state machine controlling agent execution."""

    # Explicit whitelist of valid transitions: current_state -> set(allowed_next_states)
    _VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
        AgentState.IDLE: {
            AgentState.ANALYZING,
            AgentState.UNDERSTANDING,
            AgentState.CONTEXT_RETRIEVAL,
            AgentState.ENVIRONMENT_DISCOVERY,
            AgentState.PLANNING,
            AgentState.EXECUTING,
            AgentState.CANCELLED,
        },
        AgentState.UNDERSTANDING: {
            AgentState.CONTEXT_RETRIEVAL,
            AgentState.ENVIRONMENT_DISCOVERY,
            AgentState.PLANNING,
            AgentState.WAITING_FOR_USER,
            AgentState.WAITING_FOR_INPUT,
            AgentState.EXECUTING,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.CONTEXT_RETRIEVAL: {
            AgentState.ENVIRONMENT_DISCOVERY,
            AgentState.PLANNING,
            AgentState.UNDERSTANDING,
            AgentState.WAITING_FOR_USER,
            AgentState.WAITING_FOR_INPUT,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.ENVIRONMENT_DISCOVERY: {
            AgentState.PLANNING,
            AgentState.EXECUTING,
            AgentState.CONTEXT_RETRIEVAL,
            AgentState.WAITING_FOR_USER,
            AgentState.WAITING_FOR_INPUT,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.ANALYZING: {
            AgentState.UNDERSTANDING,
            AgentState.CONTEXT_RETRIEVAL,
            AgentState.ENVIRONMENT_DISCOVERY,
            AgentState.PLANNING,
            AgentState.EXECUTING,
            AgentState.WAITING_FOR_INPUT,
            AgentState.WAITING_FOR_USER,
            AgentState.COMPLETED,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.PLANNING: {
            AgentState.PLAN_READY,
            AgentState.ENVIRONMENT_DISCOVERY,
            AgentState.REPLANNING,
            AgentState.WAITING_FOR_INPUT,
            AgentState.WAITING_FOR_USER,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.PLAN_READY: {
            AgentState.EXECUTING,
            AgentState.WAITING_FOR_APPROVAL,
            AgentState.PLANNING,
            AgentState.REPLANNING,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.WAITING_FOR_APPROVAL: {
            AgentState.EXECUTING,
            AgentState.REPLANNING,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.WAITING_FOR_INPUT: {
            AgentState.ANALYZING,
            AgentState.UNDERSTANDING,
            AgentState.PLANNING,
            AgentState.EXECUTING,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.WAITING_FOR_USER: {
            AgentState.ANALYZING,
            AgentState.UNDERSTANDING,
            AgentState.PLANNING,
            AgentState.EXECUTING,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.EXECUTING: {
            AgentState.EXECUTING,  # Step-to-step self-transition
            AgentState.VERIFYING,
            AgentState.ANALYZING,  # Transition to analyze new goal or prompt
            AgentState.WAITING_FOR_APPROVAL,
            AgentState.WAITING_FOR_INPUT,
            AgentState.WAITING_FOR_USER,
            AgentState.REPLANNING,
            AgentState.RECOVERING,
            AgentState.COMPLETED,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.VERIFYING: {
            AgentState.COMPLETED,
            AgentState.EXECUTING,
            AgentState.RECOVERING,
            AgentState.REPLANNING,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.RECOVERING: {
            AgentState.PLANNING,
            AgentState.EXECUTING,
            AgentState.VERIFYING,
            AgentState.REPLANNING,
            AgentState.WAITING_FOR_USER,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.REPLANNING: {
            AgentState.PLAN_READY,
            AgentState.EXECUTING,
            AgentState.WAITING_FOR_INPUT,
            AgentState.WAITING_FOR_USER,
            AgentState.COMPLETED,
            AgentState.FAILED,
            AgentState.CANCELLED,
            AgentState.IDLE,
        },
        AgentState.COMPLETED: {
            AgentState.IDLE,
            AgentState.ANALYZING,
            AgentState.UNDERSTANDING,
        },
        AgentState.FAILED: {
            AgentState.IDLE,
            AgentState.ANALYZING,
            AgentState.UNDERSTANDING,
            AgentState.REPLANNING,
            AgentState.RECOVERING,
        },
        AgentState.CANCELLED: {
            AgentState.IDLE,
            AgentState.ANALYZING,
            AgentState.UNDERSTANDING,
        },
    }

    def __init__(
        self,
        initial_state: AgentState = AgentState.IDLE,
        session_id: str | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._state: AgentState = initial_state
        self._session_id = session_id or ""
        self._task_id: str | None = None
        self._event_bus = event_bus
        self._history: list[StateTransitionRecord] = []

    @property
    def current_state(self) -> AgentState:
        with self._lock:
            return self._state

    @property
    def session_id(self) -> str:
        with self._lock:
            return self._session_id

    @session_id.setter
    def session_id(self, sid: str) -> None:
        with self._lock:
            self._session_id = sid

    @property
    def task_id(self) -> str | None:
        with self._lock:
            return self._task_id

    @task_id.setter
    def task_id(self, tid: str | None) -> None:
        with self._lock:
            self._task_id = tid

    def can_transition(self, target_state: AgentState) -> bool:
        """Check whether transitioning to target_state is legal from current state."""
        with self._lock:
            allowed = self._VALID_TRANSITIONS.get(self._state, set())
            return target_state in allowed

    def transition_to(
        self,
        target_state: AgentState,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AgentState:
        """Atomically validate and execute a state transition.

        Raises:
            InvalidStateTransitionError: If the transition is prohibited by state machine policy.
        """
        with self._lock:
            if not self.can_transition(target_state):
                logger.error(
                    f"Illegal state transition attempted: {self._state.value} -> {target_state.value} ({reason})"
                )
                raise InvalidStateTransitionError(self._state, target_state, reason=reason)

            old_state = self._state
            self._state = target_state

            record = StateTransitionRecord(
                from_state=old_state,
                to_state=target_state,
                reason=reason,
                metadata=metadata or {},
            )
            self._history.append(record)

            logger.info(
                f"[State Transition] {old_state.value} -> {target_state.value} (session={self._session_id}): {reason}"
            )

            # Publish event if event_bus is configured
            if self._event_bus:
                self._event_bus.publish(
                    AgentEvent(
                        event_type=AgentEventType.AGENT_STATUS_CHANGED,
                        payload={
                            "session_id": self._session_id,
                            "task_id": self._task_id,
                            "old_state": old_state.value,
                            "new_state": target_state.value,
                            "reason": reason,
                            "timestamp": record.timestamp.isoformat(),
                        },
                    )
                )

            return self._state

    def get_history(self) -> list[StateTransitionRecord]:
        """Return a copy of the transition history for auditing and diagnostics."""
        with self._lock:
            return list(self._history)

    def reset(self, new_session_id: str | None = None) -> None:
        """Reset state machine back to IDLE for a fresh task or session."""
        with self._lock:
            self._state = AgentState.IDLE
            if new_session_id is not None:
                self._session_id = new_session_id
            self._task_id = None
            self._history.clear()
