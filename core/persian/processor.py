"""Persian Language Processor: Unified Orchestrator for Persian Intelligence & Bilingual Conversation.

Coordinates normalization, entity extraction, intent analysis, reference resolution,
language policy, and multilingual response formatting.
"""

from __future__ import annotations

import time

from core.persian.context_resolver import ConversationContextResolver
from core.persian.entity_extractor import PersianEntityExtractor
from core.persian.intent_analyzer import PersianIntentAnalyzer
from core.persian.language_policy import LanguagePolicyManager, ResponseLanguage
from core.persian.models import PersianIntentType, PersianUnderstandingResult
from core.persian.normalizer import PersianTextNormalizer
from core.persian.response_controller import MultilingualResponseController
from infrastructure.logging import get_logger

logger = get_logger("persian.processor")


class PersianLanguageProcessor:
    """Central processor for Persian and bilingual natural language understanding."""

    def __init__(self) -> None:
        self.normalizer = PersianTextNormalizer()
        self.entity_extractor = PersianEntityExtractor()
        self.intent_analyzer = PersianIntentAnalyzer()
        self.context_resolver = ConversationContextResolver()
        self.language_policy = LanguagePolicyManager(default_language=ResponseLanguage.ENGLISH)
        self.response_controller = MultilingualResponseController()

    def process(self, raw_text: str) -> PersianUnderstandingResult:
        """Convenience alias for process_input."""
        return self.process_input(raw_text)

    def process_input(self, raw_text: str) -> PersianUnderstandingResult:
        """Process user input text end-to-end and produce structured understanding.

        Args:
            raw_text: Raw user utterance in Persian or mixed Persian-English.

        Returns:
            PersianUnderstandingResult with intent, entities, constraints, and policy directives.
        """
        start_time = time.perf_counter()

        # 1. Text normalization
        normalized_text = self.normalizer.normalize(raw_text)
        detected_lang = self.normalizer.detect_language(raw_text)

        # 2. Intent analysis
        primary_intent, intent_conf, is_ambig, is_hypo, clarify_msg = (
            self.intent_analyzer.analyze_intent(normalized_text)
        )

        # 3. Entity extraction
        entities = self.entity_extractor.extract_entities(raw_text, normalized_text)

        # 4. Context & reference resolution
        resolved_refs, unresolved_refs, prohibitions, read_only = (
            self.context_resolver.resolve_turn(
                raw_text=raw_text,
                normalized_text=normalized_text,
                intent=primary_intent,
                entities=entities,
            )
        )

        # 5. Language policy evaluation
        target_lang, switch_type, switch_reason = self.language_policy.evaluate_request(
            normalized_text
        )

        # If user explicitly requested language switch intent
        if primary_intent == PersianIntentType.LANGUAGE_SWITCH:
            # Clarification message or acknowledgment
            if target_lang == ResponseLanguage.PERSIAN:
                clarify_msg = "از این به بعد به فارسی پاسخ می‌دهم قربان."
            else:
                clarify_msg = "Understood, sir. Switching back to British English."

        # 6. Generate immediate acknowledgment if appropriate
        target_name: str | None = None
        for ent in entities:
            if ent.entity_type.value in ("project_name", "file_name", "application"):
                target_name = str(ent.normalized_value)
                break

        ack_text = self.response_controller.generate_acknowledgment(
            intent_name=primary_intent.value,
            language=target_lang,
            target_name=target_name,
        )

        # Build understanding result
        result = PersianUnderstandingResult(
            raw_input=raw_text,
            normalized_text=normalized_text,
            detected_language=detected_lang,
            primary_intent=primary_intent,
            intent_confidence=intent_conf,
            extracted_entities=entities,
            resolved_references=resolved_refs,
            unresolved_references=unresolved_refs,
            is_hypothetical=is_hypo,
            is_ambiguous=is_ambig,
            requires_clarification=is_ambig,
            clarification_prompt=clarify_msg,
            operational_constraints=prohibitions,
            prohibited_actions=prohibitions,
            is_read_only=read_only,
            active_project=self.context_resolver.active_project,
            active_file=self.context_resolver.active_file,
            response_language=target_lang.value,
            spoken_acknowledgment=ack_text,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "Persian processed in %.2fms: intent=%s, entities=%d, lang=%s, hypo=%s, ambig=%s",
            elapsed_ms,
            primary_intent.value,
            len(entities),
            target_lang.value,
            is_hypo,
            is_ambig,
        )

        return result

    def format_response(
        self,
        raw_llm_response: str,
        understanding: PersianUnderstandingResult,
    ) -> tuple[str, str]:
        """Format and sanitize LLM response for UI and voice output according to policy."""
        lang = ResponseLanguage(understanding.response_language)
        display_text, spoken_text = self.response_controller.prepare_response(
            raw_llm_response=raw_llm_response,
            language=lang,
        )
        return display_text, spoken_text

    def record_completed_turn(
        self,
        understanding: PersianUnderstandingResult,
        response_text: str,
    ) -> None:
        """Record completed interaction into multi-turn dialogue memory."""
        self.context_resolver.record_turn(
            user_raw_text=understanding.raw_input,
            normalized_text=understanding.normalized_text,
            intent=understanding.primary_intent,
            entities=understanding.extracted_entities,
            response_language=understanding.response_language,
            metadata={"response_len": len(response_text)},
        )

    def get_system_prompt_addition(self) -> str:
        """Get the dynamic system prompt directive reflecting current language policy."""
        return self.language_policy.get_system_directive()

    def reset(self) -> None:
        """Reset conversation context and return to default language policy."""
        self.context_resolver.reset()
        self.language_policy.reset()
