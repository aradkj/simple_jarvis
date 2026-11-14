"""NDJSON Stream Parser for Antigravity Coding Agent Subsystem."""

from __future__ import annotations

import json
from typing import Any

from infrastructure.logging import get_logger
from tools.coding_agent.models import StreamEvent

logger = get_logger("stream_parser")

SOFT_DENIAL_PATTERNS = [
    "i cannot perform this operation",
    "permission denied by safety guidelines",
    "access to system files is restricted",
    "i am not permitted to modify",
]


class StreamParser:
    """Parses NDJSON lines produced by agy CLI --output-format stream-json."""

    def __init__(self) -> None:
        self.conversation_id: str | None = None
        self.accumulated_text: list[str] = []
        self.final_result: dict[str, Any] | None = None
        self.detected_soft_denial: bool = False

    def parse_line(self, raw_line: str) -> StreamEvent | None:
        """Parse a single line of NDJSON from agy stream."""
        line = raw_line.strip()
        if not line:
            return None

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            # Non-json logging or error line from CLI
            logger.debug(f"Non-JSON line in agy stream: {line[:120]}")
            return StreamEvent(event_type="raw_output", text_delta=line + "\n")

        # Case 1: Streamed event structure: {"event": "...", ...}
        event_type = payload.get("event")
        if event_type:
            if event_type == "init":
                self.conversation_id = payload.get("conversation_id")
                return StreamEvent(event_type="init", data=payload.get("init", {}))

            elif event_type == "step_update":
                step_data = payload.get("step_update", {})
                if not self.conversation_id:
                    self.conversation_id = step_data.get("conversation_id")
                delta = step_data.get("text_delta", "")
                if delta:
                    self.accumulated_text.append(delta)
                    self._check_soft_denial(delta)
                return StreamEvent(event_type="step_update", data=step_data, text_delta=delta)

            elif event_type == "result":
                res_data = payload.get("result", {})
                self.final_result = res_data
                if not self.conversation_id:
                    self.conversation_id = res_data.get("conversation_id")
                resp = res_data.get("response", "")
                if resp and not self.accumulated_text:
                    self.accumulated_text.append(resp)
                return StreamEvent(event_type="result", data=res_data, text_delta=resp)

            else:
                return StreamEvent(event_type=event_type, data=payload)

        # Case 2: One-shot JSON response: {"conversation_id": "...", "status": "SUCCESS", "response": "..."}
        if "response" in payload or "conversation_id" in payload:
            self.conversation_id = payload.get("conversation_id")
            self.final_result = payload
            resp = payload.get("response", "")
            if resp:
                self.accumulated_text.append(resp)
                self._check_soft_denial(resp)
            return StreamEvent(event_type="result", data=payload, text_delta=resp)

        return StreamEvent(event_type="unknown", data=payload)

    def _check_soft_denial(self, text: str) -> None:
        low = text.lower()
        if any(pat in low for pat in SOFT_DENIAL_PATTERNS):
            self.detected_soft_denial = True

    def get_full_response(self) -> str:
        """Return all text deltas concatenated."""
        if self.final_result and self.final_result.get("response"):
            return self.final_result["response"]
        return "".join(self.accumulated_text)
