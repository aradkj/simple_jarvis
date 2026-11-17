"""Persian Entity Extractor for domain, project, file, application, and technical entities."""

from __future__ import annotations

import re
from pathlib import Path

from core.persian.models import PersianEntity, PersianEntityType


class PersianEntityExtractor:
    """Extracts typed entities from normalized and raw Persian/English user utterances."""

    KNOWN_PROJECTS = {
        "pc shop": ["pc shop", "pcshop", "پیسیشاپ", "پی سی شاپ", "فروشگاه کامپیوتر"],
        "document processing": ["document processing", "doc processing", "پردازش سند", "داکیومنت"],
        "jarvis": ["jarvis", "جارویس", "دستیار"],
    }

    KNOWN_APPS = {
        "notepad": ["notepad", "نوت‌پد", "نوتپد", "دفترچه یادداشت", "یادداشت"],
        "calculator": ["calculator", "ماشین حساب", "ماشین‌حساب", "calc"],
        "chrome": ["chrome", "کروم", "گوگل کروم"],
        "edge": ["edge", "ایج", "اج", "مرورگر اج", "مرورگر ایج", "مایکروسافت ایج"],
        "terminal": ["terminal", "ترمینال", "کامند لاین", "cmd", "powershell", "wt"],
        "taskmgr": ["task manager", "تسک منیجر", "مدیریت وظایف", "taskmgr"],
        "paint": ["paint", "پینت", "نقاشی", "mspaint"],
        "vscode": ["vscode", "vs code", "کد", "ویژوال استودیو"],
    }

    TECH_STACKS = [
        "fastapi",
        "docker",
        "postgresql",
        "sqlite",
        "pytest",
        "alembic",
        "gemini",
        "elevenlabs",
        "antigravity",
        "windows",
        "linux",
        "python",
        "github",
        "git",
        "rest",
        "api",
        "redis",
        "nginx",
        "react",
        "vue",
    ]

    def __init__(self, registered_projects: dict[str, Path] | None = None) -> None:
        self.registered_projects = registered_projects or {}

    def extract_entities(
        self, text: str, normalized_text: str | None = None
    ) -> list[PersianEntity]:
        """Extract all identifiable entities with type, canonical name, and confidence."""
        if not text and not normalized_text:
            return []

        entities: list[PersianEntity] = []
        combined_text = f"{text or ''} {normalized_text or ''}"
        lower = combined_text.lower()

        # 1. Extract Projects
        # A. From dynamic registered projects
        for proj_name, proj_path in self.registered_projects.items():
            if proj_name.lower() in lower:
                entities.append(
                    PersianEntity(
                        entity_type=PersianEntityType.PROJECT,
                        name=proj_name,
                        value=str(proj_path),
                        original_text=proj_name,
                        confidence=1.0,
                    )
                )

        # B. From known project catalog
        for canon_proj, aliases in self.KNOWN_PROJECTS.items():
            for alias in aliases:
                if alias in lower and not any(
                    e.name.lower() == canon_proj
                    for e in entities
                    if e.entity_type == PersianEntityType.PROJECT
                ):
                    entities.append(
                        PersianEntity(
                            entity_type=PersianEntityType.PROJECT,
                            name="PC Shop" if canon_proj == "pc shop" else canon_proj,
                            value=canon_proj,
                            original_text=alias,
                            confidence=0.95,
                        )
                    )
                    break

        # C. Generic project pattern ("پروژه X")
        proj_matches = re.finditer(
            r"(?:پروژه(?:‌ی|ی)?|ریپو(?:ی)?|مخزن)\s+([a-zA-Z0-9_\u0600-\u06ff-]+)",
            text,
            re.IGNORECASE,
        )
        for pm in proj_matches:
            p_val = pm.group(1).strip()
            if not any(
                e.name.lower() == p_val.lower()
                for e in entities
                if e.entity_type == PersianEntityType.PROJECT
            ):
                entities.append(
                    PersianEntity(
                        entity_type=PersianEntityType.PROJECT,
                        name=p_val,
                        value=p_val,
                        original_text=pm.group(0),
                        confidence=0.85,
                    )
                )

        # 2. Extract Files & Paths
        file_pattern = re.compile(
            r"(?:[a-zA-Z]:\\|\b/)[^\s\"'<>|]+|\b[a-zA-Z0-9_.-]+\.(?:py|json|txt|md|html?|css|js|ts|sql|yaml|yml|log|csv|ini|toml)\b",
            re.IGNORECASE,
        )
        for fm in file_pattern.finditer(text):
            f_val = fm.group(0).strip()
            entities.append(
                PersianEntity(
                    entity_type=PersianEntityType.FILE,
                    name=f_val,
                    value=f_val,
                    original_text=f_val,
                    confidence=1.0,
                )
            )

        # Generic file keyword pattern ("فایل X")
        file_kw_matches = re.finditer(r"(?:فایل(?:ِ)?|سند)\s+([a-zA-Z0-9_.-]+)", text, re.IGNORECASE)
        for fkm in file_kw_matches:
            target = fkm.group(1).strip()
            if not any(
                e.name.lower() == target.lower()
                for e in entities
                if e.entity_type == PersianEntityType.FILE
            ):
                entities.append(
                    PersianEntity(
                        entity_type=PersianEntityType.FILE,
                        name=target,
                        value=target,
                        original_text=fkm.group(0),
                        confidence=0.85,
                    )
                )

        # 3. Extract Applications
        for app_canon, aliases in self.KNOWN_APPS.items():
            for alias in aliases:
                if alias in lower and not any(
                    e.name.lower() == app_canon
                    for e in entities
                    if e.entity_type == PersianEntityType.APPLICATION
                ):
                    display = (
                        "Notepad"
                        if app_canon == "notepad"
                        else (
                            "Calculator"
                            if app_canon == "calculator"
                            else (
                                "Google Chrome"
                                if app_canon == "chrome"
                                else (
                                    "Microsoft Edge" if app_canon == "edge" else app_canon.title()
                                )
                            )
                        )
                    )
                    entities.append(
                        PersianEntity(
                            entity_type=PersianEntityType.APPLICATION,
                            name=display,
                            value=app_canon,
                            original_text=alias,
                            confidence=0.95,
                        )
                    )
                    break

        # 4. Extract Technical Stack / Frameworks
        for tech in self.TECH_STACKS:
            if re.search(rf"\b{re.escape(tech)}\b", lower):
                entities.append(
                    PersianEntity(
                        entity_type=PersianEntityType.TECH_STACK,
                        name=tech,
                        value=tech,
                        original_text=tech,
                        confidence=0.95,
                    )
                )

        # 5. Extract Ports
        port_match = re.search(r"(?:پورت|port)\s*[:=]?\s*(\d{2,5})", lower)
        if port_match:
            port_val = int(port_match.group(1))
            entities.append(
                PersianEntity(
                    entity_type=PersianEntityType.PORT,
                    name=str(port_val),
                    value=port_val,
                    original_text=port_match.group(0),
                    confidence=1.0,
                )
            )

        # 6. Extract Email Addresses
        email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
        if email_match:
            entities.append(
                PersianEntity(
                    entity_type=PersianEntityType.EMAIL,
                    name=email_match.group(0),
                    value=email_match.group(0),
                    original_text=email_match.group(0),
                    confidence=1.0,
                )
            )

        # 7. Extract Phone Numbers
        phone_match = re.search(r"(?:\+98|0)?9\d{9}\b", text)
        if phone_match:
            entities.append(
                PersianEntity(
                    entity_type=PersianEntityType.PHONE,
                    name=phone_match.group(0),
                    value=phone_match.group(0),
                    original_text=phone_match.group(0),
                    confidence=1.0,
                )
            )

        # 8. Extract Percentages / Metrics
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|درصد)", text)
        if pct_match:
            entities.append(
                PersianEntity(
                    entity_type=PersianEntityType.METRIC,
                    name=f"{pct_match.group(1)}%",
                    value=float(pct_match.group(1)),
                    original_text=pct_match.group(0),
                    confidence=1.0,
                )
            )

        return entities
