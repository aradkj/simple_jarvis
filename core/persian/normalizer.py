"""Persian Text Normalizer for natural colloquial and technical language processing."""

from __future__ import annotations

import re
from typing import Any


class PersianTextNormalizer:
    """Normalizes Persian orthography, colloquialisms, numerals, and punctuation

    while strictly preserving technical identifiers, code, URLs, and file paths.
    """

    # Arabic to Persian character mapping
    ARABIC_TO_PERSIAN_CHARS = {
        "\u0643": "\u06a9",  # ك -> ک
        "\u064a": "\u06cc",  # ي -> ی
        "\u0649": "\u06cc",  # ى -> ی
        "\u0629": "\u0647",  # ة -> ه
        "\u06c0": "\u0647\u200c",  # ۀ -> ه‌
    }

    # Numerals mapping (Arabic & Persian to Western standard for uniform parsing)
    NUMERALS_MAP = {
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }

    # Multi-word colloquial phrase mappings (processed before word splitting)
    COLLOQUIAL_PHRASES: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\bیه\s*کاریش\s*بکن\b", re.IGNORECASE), "بررسی و اصلاحش کن"),
        (re.compile(r"\bببین\s*مشکلش\s*چیه\b", re.IGNORECASE), "بررسی کن مشکلش چیست"),
        (re.compile(r"\bهمون\s*پروژه\s*قبلی\b", re.IGNORECASE), "پروژه قبلی"),
        (re.compile(r"\bاون\s*قسمتو\s*درست\s*کن\b", re.IGNORECASE), "آن بخش را اصلاح کن"),
        (
            re.compile(r"\bیه\s*جوری\s*انجامش\s*بده\s*که\s*دیگه\s*خراب\s*نشه\b", re.IGNORECASE),
            "به شکل پایدار اصلاحش کن",
        ),
        (
            re.compile(r"\bحواست\s*باشه\s*چیزی\s*از\s*بین\s*نره\b", re.IGNORECASE),
            "دقت کن داده‌ای حذف نشود",
        ),
        (re.compile(r"\bفعلاً\s*بیخیالش\s*شو\b", re.IGNORECASE), "صرف‌نظر کن"),
        (re.compile(r"\bفعلا\s*بیخیالش\s*شو\b", re.IGNORECASE), "صرف‌نظر کن"),
        (re.compile(r"\bبیخیالش\s*شو\b", re.IGNORECASE), "صرف‌نظر کن"),
        (re.compile(r"\bبی‌خیالش\s*شو\b", re.IGNORECASE), "صرف‌نظر کن"),
        (re.compile(r"\bخودت\s*تصمیم\s*بگیر\b", re.IGNORECASE), "به صورت خودکار تصمیم بگیر"),
        (re.compile(r"\bبرو\s*ببین\s*چی\s*شده\b", re.IGNORECASE), "وضعیت را بررسی کن"),
        (re.compile(r"\bتا\s*آخرش\s*انجامش\s*بده\b", re.IGNORECASE), "فرایند را کامل انجام بده"),
        (
            re.compile(r"\bاین\s*یکی\s*رو\s*هم\s*به\s*قبلی\s*اضافه\s*کن\b", re.IGNORECASE),
            "این مورد را هم به قبلی اضافه کن",
        ),
        (re.compile(r"\bدست\s*بهش\s*نزن\b", re.IGNORECASE), "تغییر نده"),
        (re.compile(r"\bدست\s*نزن\b", re.IGNORECASE), "تغییر نده"),
        (re.compile(r"\bخرابش\s*نکن\b", re.IGNORECASE), "خراب نکن"),
        (re.compile(r"\bحلش\s*کن\b", re.IGNORECASE), "اصلاحش کن"),
        (re.compile(r"\bاوکیش\s*کن\b", re.IGNORECASE), "اصلاحش کن"),
    ]

    # Colloquial word mappings (mapped carefully to preserve semantics)
    COLLOQUIAL_MAP: dict[str, str] = {
        "واسه": "برای",
        "واسم": "برای من",
        "واست": "برای تو",
        "واسش": "برای او",
        "میخوام": "می‌خواهم",
        "میخوای": "می‌خواهی",
        "میخواد": "می‌خواهد",
        "میخوایم": "می‌خواهیم",
        "میخواین": "می‌خواهید",
        "میخوان": "می‌خواهند",
        "نمیتونم": "نمی‌توانم",
        "نمیتونی": "نمی‌توانی",
        "نمیتونه": "نمی‌تواند",
        "نمیتونیم": "نمی‌توانیم",
        "نمیتونین": "نمی‌توانید",
        "نمیتونن": "نمی‌توانند",
        "میتونم": "می‌توانم",
        "میتونی": "می‌توانی",
        "میتونه": "می‌تواند",
        "میتونیم": "می‌توانیم",
        "میتونین": "می‌توانید",
        "میتونن": "می‌توانند",
        "چیکار": "چه کار",
        "چجوری": "چگونه",
        "چطور": "چگونه",
        "ببینش": "بررسی‌اش کن",
        "درستش کن": "اصلاحش کن",
        "پاکش کن": "حذفش کن",
        "بازش کن": "باز کن",
        "ببندش": "ببند",
        "چک کن": "بررسی کن",
        "ران کن": "اجرا کن",
        "استارت بزن": "شروع کن",
        "دست نزن": "تغییر نده",
        "بیخیال": "صرف‌نظر",
        "بی‌خیال": "صرف‌نظر",
        "ولش": "رها",
        "سریعتر": "سریع‌تر",
        "بهتره": "بهتر است",
        "میشه": "می‌شود",
        "نمیشه": "نمی‌شود",
        "باشه": "بسیار خوب",
        "مرسی": "ممنون",
    }

    ZWNJ = "\u200c"

    def __init__(self) -> None:
        # Regex patterns for protected tokens
        self._code_pattern = re.compile(r"`[^`]*`|```[\s\S]*?```")
        self._url_pattern = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
        self._path_pattern = re.compile(
            r"(?:[a-zA-Z]:\\|\b/)[^\s\"'<>|]+|\b[a-zA-Z0-9_.-]+\.(?:py|json|txt|md|html?|css|js|ts|sql|yaml|yml|log|csv|exe|dll)\b",
            re.IGNORECASE,
        )
        self._identifier_pattern = re.compile(
            r"\b(?:FastAPI|Docker|PostgreSQL|SQLite|Pytest|Alembic|Gemini|ElevenLabs|Antigravity|Windows|Linux|Python|REST|API|HTTP|GitHub|Git|CLI|IDE|Commit|Branch|Deployment|Authentication|Database|Repository|pytest|git|npm|pip|pnpm|yarn|node|uvicorn|gunicorn|alembic|sqlalchemy|pydantic|redis|nginx|curl|bash|powershell|cmd)\b",
            re.IGNORECASE,
        )
        self._env_var_pattern = re.compile(
            r"\b[A-Z][A-Z0-9_]{2,}\b|\$[A-Za-z0-9_]+|%[A-Za-z0-9_]+%"
        )
        self._cli_arg_pattern = re.compile(r"(?<=\s)(?:--[a-zA-Z0-9_-]+|-[a-zA-Z0-9])\b")
        self._port_pattern = re.compile(
            r"\b(?::[0-9]{2,5}|localhost:[0-9]{2,5}|127\.0\.0\.1:[0-9]{2,5})\b", re.IGNORECASE
        )

    def protect_tokens(self, text: str) -> tuple[str, dict[str, str]]:
        """Extract and mask technical identifiers, code, URLs, paths, and flags with placeholders."""
        if not text:
            return "", {}

        token_map: dict[str, str] = {}
        idx = 0

        def _protect(match: re.Match[str]) -> str:
            nonlocal idx
            token = match.group(0)
            placeholder = f"__PROT_TOK_{idx}__"
            token_map[placeholder] = token
            idx += 1
            return placeholder

        s = self._code_pattern.sub(_protect, text)
        s = self._url_pattern.sub(_protect, s)
        s = self._path_pattern.sub(_protect, s)
        s = self._port_pattern.sub(_protect, s)
        s = self._cli_arg_pattern.sub(_protect, s)
        s = self._env_var_pattern.sub(_protect, s)
        s = self._identifier_pattern.sub(_protect, s)
        return s, token_map

    def restore_tokens(self, text: str, token_map: dict[str, str]) -> str:
        """Restore protected tokens from their placeholder mapping."""
        if not text or not token_map:
            return text
        result = text
        for placeholder, original in token_map.items():
            result = result.replace(placeholder, original)
        return result

    def normalize(self, text: str) -> str:
        """Normalize Persian text while strictly preserving technical identifiers, code, and paths."""
        if not text:
            return ""

        # Step 1: Protect URLs, code blocks, paths, and technical identifiers with placeholders
        s, token_map = self.protect_tokens(text)

        # Step 2: Unify Arabic characters to Persian standard
        for ar, fa in self.ARABIC_TO_PERSIAN_CHARS.items():
            s = s.replace(ar, fa)

        # Step 3: Remove Arabic diacritics / harakat (tashkeel except hamza above handled in Step 6.4)
        s = re.sub(r"[\u064b-\u0652\u0655-\u0658]", "", s)

        # Step 4: Standardize numerals (Arabic/Persian -> Western)
        for num, western in self.NUMERALS_MAP.items():
            s = s.replace(num, western)

        # Step 5: Standardize Persian punctuation and quotes
        s = s.replace("«", '"').replace("»", '"')
        s = s.replace("“", '"').replace("”", '"')
        # Standardize ellipses
        s = re.sub(r"\.{3,}", "…", s)
        # Collapse repeated question / exclamation marks
        s = re.sub(r"[؟?]{2,}", "؟", s)
        s = re.sub(r"[!]{2,}", "!", s)

        # Step 6: ZWNJ (Zero-Width Non-Joiner) normalization
        # Collapse multiple ZWNJs
        s = re.sub(r"\u200c+", self.ZWNJ, s)
        # Remove ZWNJ at word boundaries
        s = re.sub(r"\s+\u200c+|\u200c+\s+", " ", s)
        s = re.sub(r"^\u200c+|\u200c+$", "", s, flags=re.MULTILINE)

        # Insert ZWNJ on verbal prefixes "می" and "نمی" if followed by space and Persian verb
        s = re.sub(r"\b(ن?می)\s+([آ-ی])", rf"\1{self.ZWNJ}\2", s)

        # Insert ZWNJ on common plural/comparative suffixes
        s = re.sub(r"([آ-ی])\s+(ها|های|تر|ترین|ام|ات|اش|مان|تان|شان)\b", rf"\1{self.ZWNJ}\2", s)

        # Step 6.4: Hamzeh, Ezāfe, and informal suffix normalization
        s = re.sub(r"([آ-ی])\s*ء", rf"\1{self.ZWNJ}", s)
        s = re.sub(r"([آ-ی])([ٔ\u0654]|\u06c0)", rf"\1{self.ZWNJ}", s)

        # Step 6.5: Collapse repeated characters (e.g. سلاااام -> سلام, خوبیییی -> خوبی, پرووژه -> پروژه)
        s = re.sub(r"([آ-یa-zA-Z])\1{2,}", r"\1", s)
        s = re.sub(r"(پرو)و+(ژه)", r"\1\2", s)
        s = re.sub(r"([رو])\1{2,}", r"\1", s)

        # Step 6.6: Multi-word colloquial phrases
        for phrase_pat, replacement in self.COLLOQUIAL_PHRASES:
            s = phrase_pat.sub(replacement, s)

        # Step 7: Normalize colloquial expressions & object marker "رو"
        # "رو" after a word as accusative marker -> "را"
        s = re.sub(r"([آ-ی0-9_])\s+رو\b", r"\1 را", s)

        # Colloquial vocabulary normalization
        words = s.split()
        normalized_words: list[str] = []
        for w in words:
            # Check direct match
            clean_w = w.strip('،؛؟?!."')
            if clean_w in self.COLLOQUIAL_MAP:
                replacement = self.COLLOQUIAL_MAP[clean_w]
                w = w.replace(clean_w, replacement)
            normalized_words.append(w)
        s = " ".join(normalized_words)

        # Step 8: Collapse redundant whitespaces
        s = re.sub(r"[ \t]+", " ", s)
        s = re.sub(r"\n\s*\n+", "\n", s).strip()

        # Step 9: Restore protected tokens
        s = self.restore_tokens(s, token_map)

        return s

    def detect_language(self, text: str) -> str:
        """Detect language category of text: 'fa' (Persian), 'en' (English), or 'mixed'."""
        if not text:
            return "en"

        persian_chars = len(re.findall(r"[\u0600-\u06ff\ufb8a\u067e\u0686\u06af]", text))
        english_chars = len(re.findall(r"[a-zA-Z]", text))

        if persian_chars > 0 and english_chars > 0:
            return "mixed"
        if persian_chars > 0:
            return "fa"
        return "en"

    def normalize_detailed(self, text: str) -> dict[str, Any]:
        """Normalize text and return detailed breakdown preserving raw and masked forms."""
        norm = self.normalize(text)
        _, tokens = self.protect_tokens(text)
        return {
            "raw_input": text,
            "normalized_text": norm,
            "detected_language": self.detect_language(text),
            "tokens": tokens,
        }
