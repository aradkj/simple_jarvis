"""Persian Text Normalizer for natural colloquial and technical language processing."""

from __future__ import annotations

import re


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
    }

    ZWNJ = "\u200c"

    def __init__(self) -> None:
        # Regex patterns for protected tokens
        self._url_pattern = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
        self._path_pattern = re.compile(
            r"(?:[a-zA-Z]:\\|\b/)[^\s\"'<>|]+|\b[a-zA-Z0-9_.-]+\.(?:py|json|txt|md|html?|css|js|ts|sql|yaml|yml|log|csv|exe|dll)\b",
            re.IGNORECASE,
        )
        self._code_pattern = re.compile(r"`[^`]*`|```[\s\S]*?```")
        self._identifier_pattern = re.compile(
            r"\b(?:FastAPI|Docker|PostgreSQL|SQLite|Pytest|Alembic|Gemini|ElevenLabs|Antigravity|Windows|Linux|Python|REST|API|HTTP|GitHub|Git)\b",
            re.IGNORECASE,
        )

    def normalize(self, text: str) -> str:
        """Normalize Persian text while strictly preserving technical identifiers, code, and paths."""
        if not text:
            return ""

        # Step 1: Protect URLs, code blocks, paths, and technical identifiers with placeholders
        protected: list[str] = []

        def _protect(match: re.Match[str]) -> str:
            token = match.group(0)
            placeholder = f"__PROT_TOK_{len(protected)}__"
            protected.append(token)
            return placeholder

        # Sequence of protections
        s = self._code_pattern.sub(_protect, text)
        s = self._url_pattern.sub(_protect, s)
        s = self._path_pattern.sub(_protect, s)
        s = self._identifier_pattern.sub(_protect, s)

        # Step 2: Unify Arabic characters to Persian standard
        for ar, fa in self.ARABIC_TO_PERSIAN_CHARS.items():
            s = s.replace(ar, fa)

        # Step 3: Remove Arabic diacritics / harakat (tashkeel)
        s = re.sub(r"[\u064b-\u0652\u0654-\u0658]", "", s)

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

        # Step 6.5: Collapse repeated characters (e.g. سلاااام -> سلام, خوبیییی -> خوبی)
        s = re.sub(r"([آ-یa-zA-Z])\1{2,}", r"\1", s)

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
        for i, token in enumerate(protected):
            s = s.replace(f"__PROT_TOK_{i}__", token)

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

    def normalize_detailed(self, text: str) -> dict[str, str]:
        """Normalize text and return a dictionary with normalized_text and detected_language."""
        return {
            "normalized_text": self.normalize(text),
            "detected_language": self.detect_language(text),
        }
