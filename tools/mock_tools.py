"""Simulated mock tools for testing Phase 3 Agent Core orchestration.

These tools strictly perform deterministic, in-memory simulations without any
real Windows, filesystem, shell, terminal, browser, or process execution.
"""

from __future__ import annotations

import ast
import operator

from pydantic import BaseModel, Field

from core.execution_context import ExecutionContext
from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult

# --- Mock Schemas ---


class SearchInput(BaseModel):
    query: str = Field(description="Search term or topic")


class CalculatorInput(BaseModel):
    expression: str = Field(description="Mathematical expression, e.g. '12 * 4'")


class WeatherInput(BaseModel):
    city: str = Field(description="Name of the city to check weather for")


class DangerousActionInput(BaseModel):
    action: str = Field(description="Description of the simulated sensitive action")
    target: str = Field(description="Target system or resource identifier")


# --- Mock Tool Implementations ---


class MockSearchTool(BaseTool):
    """Simulated search tool for informational retrieval."""

    name = "mock_search"
    description = "Search documents or knowledge base for information"
    category = PermissionCategory.READ_ONLY
    input_schema = SearchInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Search cancelled by user")
        assert isinstance(params, SearchInput)
        q = params.query.lower().strip()
        simulated_data = {
            "python": "Python is a high-level programming language created by Guido van Rossum.",
            "jarvis": "JARVIS is a modular personal AI desktop assistant built with Python and PySide6.",
            "weather": "Current atmospheric conditions are clear and mild.",
        }
        found = simulated_data.get(q, f"Simulated search results for query: '{params.query}'")
        return ToolResult.success(data={"query": params.query, "results": found})

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search term or topic"}},
                "required": ["query"],
            },
            requires_approval=False,
        )


class MockCalculatorTool(BaseTool):
    """Deterministic, safe calculator tool avoiding arbitrary code evaluation."""

    name = "mock_calculator"
    description = "Calculate basic mathematical expressions safely"
    category = PermissionCategory.COMPUTATION
    input_schema = CalculatorInput

    _OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
    }

    def _safe_eval(self, node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return self._safe_eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in self._OPERATORS:
            left = self._safe_eval(node.left)
            right = self._safe_eval(node.right)
            return self._OPERATORS[type(node.op)](left, right)
        raise ValueError("Unsupported or unsafe mathematical expression.")

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Calculation cancelled by user")
        assert isinstance(params, CalculatorInput)
        try:
            tree = ast.parse(params.expression, mode="eval")
            res = self._safe_eval(tree)
            return ToolResult.success(data={"expression": params.expression, "result": res})
        except Exception as exc:
            return ToolResult.failed(f"Calculation error: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "Math expression"}},
                "required": ["expression"],
            },
            requires_approval=False,
        )


class MockWeatherTool(BaseTool):
    """Simulated weather lookup tool."""

    name = "mock_weather"
    description = "Check current weather for a specified city"
    category = PermissionCategory.READ_ONLY
    input_schema = WeatherInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Weather query cancelled by user")
        assert isinstance(params, WeatherInput)
        return ToolResult.success(
            data={
                "city": params.city,
                "temperature_c": 22,
                "condition": "Sunny",
                "humidity": 45,
            }
        )

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"],
            },
            requires_approval=False,
        )


class MockDangerousSystemTool(BaseTool):
    """Simulated sensitive tool requiring explicit approval (NEVER performs real actions)."""

    name = "mock_dangerous_action"
    description = "Simulate a sensitive action requiring explicit user confirmation"
    category = PermissionCategory.SYSTEM
    input_schema = DangerousActionInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Sensitive action cancelled by user")
        assert isinstance(params, DangerousActionInput)
        # Note: strictly a simulated response, no real changes made
        return ToolResult.success(
            data={
                "action": params.action,
                "target": params.target,
                "simulated": True,
                "message": f"Successfully simulated '{params.action}' on '{params.target}' (no actual system modifications).",
            }
        )

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.HIGH,
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action description"},
                    "target": {"type": "string", "description": "Target identifier"},
                },
                "required": ["action", "target"],
            },
            requires_approval=True,
        )
