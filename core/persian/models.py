"""Domain Models and Type Definitions for Persian Language Intelligence & Dialogue Management.

Defines structured schemas for entity extraction, intent classification,
reference resolution, and operational understanding.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PersianIntentType(StrEnum):
    """Categories of user intent recognized in Persian and bilingual utterances."""

    GENERAL_CONVERSATION = "general_conversation"
    GREETING = "general_conversation"
    CASUAL_CHAT = "casual_chat"
    QUESTION_ANSWERING = "question_answering"
    TECHNICAL_EXPLANATION = "technical_explanation"
    CODE_EXPLANATION = "code_explanation"
    PROJECT_INVESTIGATION = "project_investigation"
    DEBUGGING = "debugging"
    CODE_MODIFICATION = "code_modification"
    CODE_EXECUTION = "code_execution"
    FILE_OPERATION = "file_operation"
    APPLICATION_CONTROL = "application_control"
    WEB_RESEARCH = "web_research"
    WEB_SEARCH = "web_search"
    TASK_PLANNING = "task_planning"
    MULTI_STEP_EXECUTION = "multi_step_execution"
    MEMORY_RECALL = "memory_recall"
    MEMORY_UPDATE = "memory_update"
    TASK_CONTINUATION = "task_continuation"
    TASK_CANCELLATION = "task_cancellation"
    LANGUAGE_SWITCH = "language_switch"
    HYPOTHETICAL_DISCUSSION = "hypothetical_discussion"
    CLARIFICATION_ANSWER = "clarification_answer"
    CONFIRMATION_OR_APPROVAL = "confirmation_or_approval"
    USER_CORRECTION = "user_correction"
    SYSTEM_DIAGNOSTICS = "system_diagnostics"
    INTEGRATION_MANAGEMENT = "integration_management"
    GIT_OPERATION = "git_operation"
    GENERAL_KNOWLEDGE = "general_knowledge"
    REFUSAL_OR_SAFETY = "refusal_or_safety"
    UNKNOWN = "unknown"


class PersianEntityType(StrEnum):
    """Types of extracted entities recognized in user utterances."""

    PROJECT = "project"
    PROJECT_NAME = "project_name"
    FILE = "file"
    FILE_NAME = "file_name"
    FILE_PATH = "file_path"
    DIRECTORY = "directory"
    APPLICATION = "application"
    APPLICATION_NAME = "application"
    PORT = "port"
    PORT_NUMBER = "port"
    TECH_STACK = "tech_stack"
    EMAIL = "email"
    PHONE = "phone"
    METRIC = "metric"
    TASK = "task"


class PersianEntity(BaseModel):
    """Represents a named or typed entity extracted from Persian text."""

    raw_text: str = ""
    normalized_value: Any = None
    entity_type: PersianEntityType
    name: str = ""
    value: Any = None
    original_text: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.raw_text and self.original_text:
            self.raw_text = self.original_text
        elif not self.original_text and self.raw_text:
            self.original_text = self.raw_text
        if self.value and (
            self.normalized_value is None or self.normalized_value == self.original_text
        ):
            self.normalized_value = self.value
        elif self.normalized_value is None and self.name:
            self.normalized_value = self.name
        elif self.normalized_value is not None and not self.name:
            self.name = str(self.normalized_value)


class PersianUnderstandingResult(BaseModel):
    """Structured understanding output containing all extracted semantic dimensions."""

    raw_input: str
    normalized_text: str
    detected_language: str = "fa"
    primary_intent: PersianIntentType
    intent_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    extracted_entities: list[PersianEntity] = Field(default_factory=list)
    resolved_references: dict[str, Any] = Field(default_factory=dict)
    unresolved_references: list[str] = Field(default_factory=list)
    is_hypothetical: bool = False
    is_ambiguous: bool = False
    requires_clarification: bool = False
    clarification_prompt: str | None = None
    operational_constraints: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    is_read_only: bool = False
    active_project: str | None = None
    active_file: str | None = None
    response_language: str = "en"
    spoken_acknowledgment: str | None = None

    @property
    def intent(self) -> PersianIntentType:
        return self.primary_intent

    @property
    def entities(self) -> list[PersianEntity]:
        return self.extracted_entities

    @property
    def safety_constraints(self) -> list[str]:
        return self.operational_constraints
