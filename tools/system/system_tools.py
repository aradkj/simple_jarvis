"""Real Windows System Information Tools for JARVIS Phase 4.

Includes:
- SystemCPUInfoTool: Real CPU metrics, clock speed, cores, and utilization.
- SystemMemoryInfoTool: Real physical and page file memory metrics.
- SystemDiskInfoTool: Real mounted disk partitions, capacities, and free space.
- SystemNetworkInfoTool: Real network adapters, status, IPs, and byte counters.
- SystemOverviewTool: Consolidated machine hardware and OS specifications.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.system.system_service import WindowsSystemService

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


# --- Pydantic Input Schemas ---


class EmptyInput(BaseModel):
    """Empty schema for tools that do not require input parameters."""

    pass


class CPUInput(BaseModel):
    sample_duration: float = Field(
        default=0.1,
        ge=0.05,
        le=1.0,
        description="Sampling duration in seconds for CPU utilization measurement",
    )


class NetworkInput(BaseModel):
    include_mac: bool = Field(
        default=False,
        description="Whether to include physical MAC addresses (subject to privacy policy)",
    )


# --- Tool Implementations ---


class SystemCPUInfoTool(BaseTool):
    """Tool to inspect real Windows CPU hardware, cores, clock speed, and current utilization."""

    name = "system_get_cpu_info"
    description = "Inspect real Windows CPU specifications, physical/logical core counts, clock frequency, and current load percentage."
    category = PermissionCategory.SYSTEM_INFO
    input_schema = CPUInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("CPU inspection cancelled by user")

        sample_dur = getattr(params, "sample_duration", 0.1)
        data = WindowsSystemService.get_cpu_info(sample_duration=sample_dur)
        return ToolResult.success(data=data)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "sample_duration": {
                        "type": "number",
                        "description": "Sampling duration in seconds (0.05 to 1.0)",
                        "default": 0.1,
                    }
                },
            },
            requires_approval=False,
            timeout_seconds=5.0,
        )


class SystemMemoryInfoTool(BaseTool):
    """Tool to inspect real Windows RAM and virtual memory utilization."""

    name = "system_get_memory_info"
    description = "Inspect real Windows physical RAM, available memory, used memory, utilization percentage, and page file usage."
    category = PermissionCategory.SYSTEM_INFO
    input_schema = EmptyInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Memory inspection cancelled by user")

        data = WindowsSystemService.get_memory_info()
        return ToolResult.success(data=data)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={"type": "object", "properties": {}},
            requires_approval=False,
            timeout_seconds=5.0,
        )


class SystemDiskInfoTool(BaseTool):
    """Tool to inspect real mounted disk drives and partition capacities."""

    name = "system_get_disk_info"
    description = "Inspect mounted Windows local disk drives, filesystem types, total capacities, and free storage."
    category = PermissionCategory.SYSTEM_INFO
    input_schema = EmptyInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Disk inspection cancelled by user")

        data = WindowsSystemService.get_disk_info()
        return ToolResult.success(data=data)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={"type": "object", "properties": {}},
            requires_approval=False,
            timeout_seconds=5.0,
        )


class SystemNetworkInfoTool(BaseTool):
    """Tool to inspect network adapters, operational status, IP addresses, and byte counters."""

    name = "system_get_network_info"
    description = "Inspect active Windows network interfaces, status, IPv4 addresses, link speeds, and transmitted byte counters."
    category = PermissionCategory.NETWORK_INSPECT
    input_schema = NetworkInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Network inspection cancelled by user")

        expose_mac = getattr(params, "include_mac", False)
        data = WindowsSystemService.get_network_info(expose_mac=expose_mac)
        return ToolResult.success(data=data)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "include_mac": {
                        "type": "boolean",
                        "description": "Whether to return MAC addresses (default False)",
                        "default": False,
                    }
                },
            },
            requires_approval=False,
            timeout_seconds=5.0,
        )


class SystemOverviewTool(BaseTool):
    """Tool to inspect a consolidated overview of OS and hardware specifications."""

    name = "system_get_overview"
    description = "Retrieve a concise, comprehensive overview of the computer's OS, CPU, RAM, disk, and network specifications."
    category = PermissionCategory.SYSTEM_INFO
    input_schema = EmptyInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("System overview cancelled by user")

        data = WindowsSystemService.get_system_overview()
        return ToolResult.success(data=data)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={"type": "object", "properties": {}},
            requires_approval=False,
            timeout_seconds=5.0,
        )
