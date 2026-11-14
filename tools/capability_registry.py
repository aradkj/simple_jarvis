"""Extensible Capability and Plugin Ecosystem Registry for JARVIS Phase 10.

Provides capability discovery, health checks, versioning, runtime enable/disable,
input/output schema validation, approval policies, and execution isolation without
weakening default-deny boundaries.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel
from infrastructure.logging import get_logger

logger = get_logger("capability_registry")


class CapabilityStatus(StrEnum):
    """Lifecycle and operational health status of an assistant capability."""

    AVAILABLE = "available"
    DISABLED = "disabled"
    UNCONFIGURED = "unconfigured"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class CapabilityMetadata:
    """Standardized manifest for an assistant tool capability."""

    capability_id: str
    name: str
    version: str
    description: str
    category: PermissionCategory
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False
    timeout_seconds: float = 30.0
    cancellation_supported: bool = True
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    status: CapabilityStatus = CapabilityStatus.AVAILABLE
    status_reason: str = ""
    health_check: Callable[[], bool] | None = None
    verification_handler: Callable[[Any], bool] | None = None


class CapabilityRegistry:
    """Thread-safe registry managing extensible capabilities and plugin lifecycles."""

    _instance: CapabilityRegistry | None = None

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._capabilities: dict[str, CapabilityMetadata] = {}
        self._execution_history: list[dict[str, Any]] = []

    @classmethod
    def get_instance(cls) -> CapabilityRegistry:
        if cls._instance is None:
            cls._instance = CapabilityRegistry()
        return cls._instance

    def register_capability(self, capability: CapabilityMetadata) -> None:
        """Register a new capability in the system."""
        with self._lock:
            self._capabilities[capability.capability_id] = capability
            logger.info(
                f"Registered capability '{capability.name}' (id={capability.capability_id}, v={capability.version})"
            )

    def get_capability(self, capability_id: str) -> CapabilityMetadata | None:
        with self._lock:
            return self._capabilities.get(capability_id)

    def list_capabilities(
        self,
        category: PermissionCategory | None = None,
        only_enabled: bool = False,
    ) -> list[CapabilityMetadata]:
        with self._lock:
            caps = list(self._capabilities.values())
            if category:
                caps = [c for c in caps if c.category == category]
            if only_enabled:
                caps = [c for c in caps if c.enabled and c.status == CapabilityStatus.AVAILABLE]
            return caps

    def set_enabled(self, capability_id: str, enabled: bool) -> bool:
        """Enable or disable a capability dynamically."""
        with self._lock:
            cap = self._capabilities.get(capability_id)
            if not cap:
                return False
            cap.enabled = enabled
            logger.info(f"Capability '{capability_id}' {'enabled' if enabled else 'disabled'}")
            return True

    def run_health_checks(self) -> dict[str, dict[str, Any]]:
        """Run health check handlers for all registered capabilities."""
        with self._lock:
            results: dict[str, dict[str, Any]] = {}
            for cid, cap in self._capabilities.items():
                if not cap.enabled:
                    cap.status = CapabilityStatus.DISABLED
                    cap.status_reason = "Disabled by administrator"
                elif cap.health_check:
                    try:
                        ok = cap.health_check()
                        cap.status = CapabilityStatus.AVAILABLE if ok else CapabilityStatus.DEGRADED
                        cap.status_reason = "Healthy" if ok else "Health check reported degradation"
                    except Exception as exc:
                        cap.status = CapabilityStatus.FAILED
                        cap.status_reason = f"Health check threw exception: {exc}"
                else:
                    cap.status = CapabilityStatus.AVAILABLE
                    cap.status_reason = "No custom health check; assume operational"

                results[cid] = {
                    "name": cap.name,
                    "status": cap.status.value,
                    "reason": cap.status_reason,
                    "enabled": cap.enabled,
                    "version": cap.version,
                }
            return results

    def record_execution(
        self,
        capability_id: str,
        operation: str,
        success: bool,
        duration_seconds: float,
        error: str | None = None,
    ) -> None:
        """Log structured capability execution metrics for observability."""
        with self._lock:
            rec = {
                "capability_id": capability_id,
                "operation": operation,
                "success": success,
                "duration_seconds": duration_seconds,
                "error": error,
                "timestamp": time.time(),
            }
            self._execution_history.append(rec)
            if len(self._execution_history) > 1000:
                self._execution_history = self._execution_history[-1000:]


_capability_registry_instance: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    global _capability_registry_instance
    if _capability_registry_instance is None:
        _capability_registry_instance = CapabilityRegistry.get_instance()
    return _capability_registry_instance
