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
    PERSON = "person"
    ORGANIZATION = "organization"
    URL = "url"
    REPOSITORY = "repository"
    BRANCH = "branch"
    COMMIT = "commit"
    COMMAND = "command"
    ARGUMENT = "argument"
    LANGUAGE = "language"
    SETTING = "setting"


class TaskComplexity(StrEnum):
    """Categorization of request/task reasoning complexity."""

    SIMPLE_CONVERSATIONAL = "simple_conversational"
    INFORMATION_RETRIEVAL = "information_retrieval"
    CONTEXT_DEPENDENT = "context_dependent"
    ANALYTICAL = "analytical"
    MULTI_STEP_PLANNING = "multi_step_planning"
    TECHNICAL_DIAGNOSIS = "technical_diagnosis"
    TOOL_EXECUTION = "tool_execution"
    HIGH_RISK_OPERATION = "high_risk_operation"
    CREATIVE_TASK = "creative_task"
    AMBIGUOUS_TASK = "ambiguous_task"


class ConfidenceLevel(StrEnum):
    """Calibrated confidence indicator based on evidence and verification."""

    VERIFIED = "verified"
    STRONGLY_SUPPORTED = "strongly_supported"
    PROBABLE = "probable"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"


class RiskLevel(StrEnum):
    """Action and execution risk classification for bounded autonomy."""

    READ_ONLY = "read_only"
    REVERSIBLE_MODIFICATION = "reversible_modification"
    EXTERNAL_COMMUNICATION = "external_communication"
    SENSITIVE_DATA_ACCESS = "sensitive_data_access"
    DESTRUCTIVE_OPERATION = "destructive_operation"
    IRREVERSIBLE_OPERATION = "irreversible_operation"


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
    secondary_intents: list[PersianIntentType] = Field(default_factory=list)
    requested_action: str = ""
    target_entity: str | None = None
    relevant_objects: list[str] = Field(default_factory=list)
    relevant_locations: list[str] = Field(default_factory=list)
    desired_outcome: str = ""
    temporal_references: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    explicit_user_preferences: list[str] = Field(default_factory=list)
    potential_risks: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    confidence_indicators: dict[str, Any] = Field(default_factory=dict)

    @property
    def intent(self) -> PersianIntentType:
        return self.primary_intent

    @property
    def entities(self) -> list[PersianEntity]:
        return self.extracted_entities

    @property
    def safety_constraints(self) -> list[str]:
        return self.operational_constraints

    def to_semantic_interpretation(self) -> SemanticInterpretation:
        """Convert understanding result into full structured SemanticInterpretation."""
        return SemanticInterpretation(
            raw_input=self.raw_input,
            normalized_text=self.normalized_text,
            detected_language=self.detected_language,
            primary_intent=self.primary_intent,
            secondary_intents=self.secondary_intents,
            requested_action=self.requested_action,
            target_entity=self.target_entity,
            relevant_objects=self.relevant_objects,
            relevant_locations=self.relevant_locations,
            constraints=self.operational_constraints,
            preconditions=[],
            desired_outcome=self.desired_outcome,
            temporal_references=self.temporal_references,
            dependencies=self.dependencies,
            explicit_user_preferences=self.explicit_user_preferences,
            potential_risks=self.potential_risks,
            ambiguities=self.ambiguities,
            confidence_indicators=self.confidence_indicators or {"intent": self.intent_confidence},
            requires_clarification=self.requires_clarification,
            clarification_prompt=self.clarification_prompt,
            is_hypothetical=self.is_hypothetical,
            is_read_only=self.is_read_only,
            extracted_entities=self.extracted_entities,
            resolved_references=self.resolved_references,
            unresolved_references=self.unresolved_references,
            active_project=self.active_project,
            active_file=self.active_file,
            response_language=self.response_language,
            spoken_acknowledgment=self.spoken_acknowledgment,
        )


class SemanticInterpretation(BaseModel):
    """Structured Semantic Interpretation Layer model satisfying Section 4 requirements."""

    raw_input: str
    normalized_text: str
    detected_language: str = "fa"
    primary_intent: PersianIntentType
    secondary_intents: list[PersianIntentType] = Field(default_factory=list)
    requested_action: str = ""
    target_entity: str | None = None
    relevant_objects: list[str] = Field(default_factory=list)
    relevant_locations: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    desired_outcome: str = ""
    temporal_references: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    explicit_user_preferences: list[str] = Field(default_factory=list)
    potential_risks: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    confidence_indicators: dict[str, Any] = Field(default_factory=dict)
    requires_clarification: bool = False
    clarification_prompt: str | None = None
    is_hypothetical: bool = False
    is_read_only: bool = False
    extracted_entities: list[PersianEntity] = Field(default_factory=list)
    resolved_references: dict[str, Any] = Field(default_factory=dict)
    unresolved_references: list[str] = Field(default_factory=list)
    active_project: str | None = None
    active_file: str | None = None
    response_language: str = "en"
    spoken_acknowledgment: str | None = None

    def to_understanding_result(self) -> PersianUnderstandingResult:
        """Convert into backward-compatible PersianUnderstandingResult."""
        return PersianUnderstandingResult(
            raw_input=self.raw_input,
            normalized_text=self.normalized_text,
            detected_language=self.detected_language,
            primary_intent=self.primary_intent,
            intent_confidence=float(self.confidence_indicators.get("intent", 1.0)),
            extracted_entities=self.extracted_entities,
            resolved_references=self.resolved_references,
            unresolved_references=self.unresolved_references,
            is_hypothetical=self.is_hypothetical,
            is_ambiguous=len(self.ambiguities) > 0 or self.requires_clarification,
            requires_clarification=self.requires_clarification,
            clarification_prompt=self.clarification_prompt,
            operational_constraints=self.constraints,
            prohibited_actions=[
                c for c in self.constraints if c.startswith("no_") or "دست نزن" in c
            ],
            is_read_only=self.is_read_only,
            active_project=self.active_project,
            active_file=self.active_file,
            response_language=self.response_language,
            spoken_acknowledgment=self.spoken_acknowledgment,
            secondary_intents=self.secondary_intents,
            requested_action=self.requested_action,
            target_entity=self.target_entity,
            relevant_objects=self.relevant_objects,
            relevant_locations=self.relevant_locations,
            desired_outcome=self.desired_outcome,
            temporal_references=self.temporal_references,
            dependencies=self.dependencies,
            explicit_user_preferences=self.explicit_user_preferences,
            potential_risks=self.potential_risks,
            ambiguities=self.ambiguities,
            confidence_indicators=self.confidence_indicators,
        )


class DecisionOption(BaseModel):
    """Candidate option evaluated during reasoning and trade-off analysis."""

    option_id: str
    title: str
    description: str
    trade_offs: dict[str, Any] = Field(
        default_factory=dict
    )  # correctness, security, complexity, time, cost
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    score: float = 0.0
    is_recommended: bool = False
    reasons: list[str] = Field(default_factory=list)


class DecisionRecord(BaseModel):
    """Structured decision record documenting decision quality and rationale (Section 7.4)."""

    decision_id: str
    objective: str
    available_evidence: list[str] = Field(default_factory=list)
    relevant_constraints: list[str] = Field(default_factory=list)
    candidate_options: list[DecisionOption] = Field(default_factory=list)
    selected_option: str
    reasons_for_selection: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    rejected_alternatives: list[dict[str, str]] = Field(default_factory=list)
    verification_requirements: list[str] = Field(default_factory=list)
    confidence_level: ConfidenceLevel = ConfidenceLevel.PROBABLE
    timestamp: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
