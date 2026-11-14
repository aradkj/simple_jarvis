"""Exceptions for the Antigravity Coding Agent Subsystem."""

from __future__ import annotations


class CodingAgentError(Exception):
    """Base exception for all coding agent errors."""


class AntigravityNotFoundError(CodingAgentError):
    """Raised when the agy executable cannot be located or verified."""


class WorkspacePolicyViolationError(CodingAgentError):
    """Raised when a workspace path violates security policy."""


class StreamParseError(CodingAgentError):
    """Raised when an unrecoverable NDJSON stream parsing error occurs."""


class TaskExecutionError(CodingAgentError):
    """Raised when task execution fails or encounters a process error."""


class VerificationFailedError(CodingAgentError):
    """Raised when independent verification fails (e.g. failing tests)."""
