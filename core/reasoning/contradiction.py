"""Contradiction Detector for JARVIS Reasoning Architecture (Section 7.6).

Detects and resolves contradictions between:
- Current instructions vs earlier instructions
- Current instructions vs retrieved memories
- Requested action vs project configuration or constraints
- Tool results vs expectations
"""

from __future__ import annotations

from typing import Any


class ContradictionDetector:
    """Identifies and resolves conflicting goals, constraints, and memory facts."""

    def detect_in_instructions(
        self,
        current_text: str,
        constraints: list[str] | None = None,
        prohibitions: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Identify contradictions inside the current request or against constraints."""
        contradictions: list[dict[str, Any]] = []
        lower = current_text.lower()
        active_constraints = constraints or []
        active_prohibitions = prohibitions or []

        # Read-only vs modification
        has_edit = any(
            k in lower
            for k in (
                "ویرایش",
                "ادیت",
                "عوض کن",
                "عوضش کن",
                "تغییر بده",
                "تغییرات",
                "اعمال کن",
                "تغییر",
                "delete",
                "remove",
                "modify",
                "edit",
                "پاک کن",
                "حذف کن",
                "حذفش کن",
                "پاکسازی",
            )
        )
        has_read_only = "read_only" in active_constraints or any(
            k in lower
            for k in (
                "فقط ببین",
                "فقط بررسی کن",
                "فقط بخوان",
                "فقط نگاه کن",
                "دست نزن",
                "دست به هیچی نزن",
                "تغییر نده",
                "تغییر ایجاد نکن",
                "چیزی تغییر نکنه",
                "بدون اینکه چیزی تغییر کنه",
                "ادیت نکن",
                "ویرایش نکن",
            )
        )
        if has_edit and has_read_only:
            contradictions.append(
                {
                    "type": "read_only_vs_modification",
                    "severity": "high",
                    "description": "Request asks to modify files while simultaneously enforcing read-only constraint.",
                    "resolution": "Preserve safety: enforce read-only constraint and request confirmation.",
                }
            )

        # Delete vs preserve
        has_preserve = "preserve_existing_data" in active_constraints or any(
            k in lower
            for k in (
                "حواست باشه چیزی از بین نره",
                "دقت کن چیزی پاک نشه",
                "اطلاعات پاک نشه",
                "حفظش کن",
                "حفظ کن",
                "بدون حذف اطلاعات",
                "اطلاعات حذف نشه",
                "داده‌ها پاک نشه",
                "بدون پاک شدن",
                "حفظ داده‌ها",
            )
        )
        has_delete = any(
            k in lower
            for k in (
                "پاک کن",
                "حذف کن",
                "حذفش کن",
                "پاکسازی",
                "دیلیت",
                "دیلیت کن",
                "delete",
                "wipe",
                "clean",
                "remove",
            )
        )
        if has_preserve and has_delete:
            contradictions.append(
                {
                    "type": "delete_vs_preserve",
                    "severity": "high",
                    "description": "Deletion requested alongside an explicit data preservation instruction.",
                    "resolution": "Preserve data: require explicit file-by-file confirmation.",
                }
            )

        # Specific prohibited target check
        for p in active_prohibitions:
            if p.startswith("do_not_touch_"):
                target = p[len("do_not_touch_") :]
                if target in lower and has_edit:
                    contradictions.append(
                        {
                            "type": "prohibited_target_modification",
                            "severity": "critical",
                            "description": f"Target '{target}' is explicitly protected by user prohibition.",
                            "resolution": "Refuse modification to protected target.",
                        }
                    )

        return contradictions

    def detect_against_memory(
        self,
        current_instruction: str,
        retrieved_memories: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Detect conflicts between current instruction and persistent preferences.

        According to Section 5.1:
        Newer explicit instructions ALWAYS override older conflicting preferences
        unless safety or authorization constraints prevent it.
        """
        conflicts: list[dict[str, Any]] = []
        lower = current_instruction.lower()

        # Language preference conflict
        if any(k in lower for k in ("فارسی", "persian", "farsi")):
            for m in retrieved_memories:
                content = str(m.get("content", "")).lower()
                if "english" in content:
                    conflicts.append(
                        {
                            "type": "language_preference_override",
                            "severity": "low",
                            "description": "Current request for Persian overrides older English preference.",
                            "resolution": "Follow latest explicit instruction (switch to Persian).",
                            "override_applied": True,
                        }
                    )

        return conflicts
