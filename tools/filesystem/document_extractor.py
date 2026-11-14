"""Document Extraction Engine for Phase 8.

Extracts text and structured metadata from common office documents and text formats:
- Plain text & Markdown (.txt, .md, .log, .rst, .ini, .yaml, .yml)
- Data formats (.json, .csv, .tsv)
- Office formats (.docx, .xlsx, .pptx) via pure-Python standard zipfile & XML parsing
- PDF (.pdf) via PySide6.QtPdf with graceful fallback

All extractions are bounded, safe, handle encoding issues, and protect against corrupted/binary files.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("document_extractor")


@dataclass
class ExtractedDocument:
    """Result of document extraction."""

    file_path: str
    file_type: str
    text_content: str
    char_count: int
    word_count: int
    line_count: int
    page_count: int = 1
    sheet_count: int = 0
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class DocumentExtractionError(Exception):
    """Raised when document extraction fails due to formatting or encryption."""


class DocumentExtractor:
    """Bounded, multi-format document extraction service."""

    SUPPORTED_EXTENSIONS = {
        ".txt",
        ".md",
        ".markdown",
        ".log",
        ".rst",
        ".ini",
        ".yaml",
        ".yml",
        ".json",
        ".csv",
        ".tsv",
        ".docx",
        ".xlsx",
        ".pptx",
        ".pdf",
    }

    def __init__(self, max_chars_default: int = 32000, max_pages_default: int = 50) -> None:
        self.max_chars_default = max_chars_default
        self.max_pages_default = max_pages_default

    def is_supported(self, file_path: Path | str) -> bool:
        """Check if file extension is supported."""
        suffix = Path(file_path).suffix.lower()
        return suffix in self.SUPPORTED_EXTENSIONS

    def extract(
        self,
        file_path: Path | str,
        max_chars: int | None = None,
        max_pages: int | None = None,
    ) -> ExtractedDocument:
        """Extract text and metadata from a document with strict bounds.

        Args:
            file_path: Path to target document.
            max_chars: Maximum characters to return.
            max_pages: Maximum pages/slides to parse.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Document not found: '{file_path}'")
        if path.is_dir():
            raise IsADirectoryError(f"Target is a directory, not a document: '{file_path}'")

        effective_max_chars = max_chars if max_chars is not None else self.max_chars_default
        effective_max_pages = max_pages if max_pages is not None else self.max_pages_default
        suffix = path.suffix.lower()

        if suffix in {".txt", ".md", ".markdown", ".log", ".rst", ".ini", ".yaml", ".yml"}:
            return self._extract_plain_text(path, effective_max_chars)
        elif suffix == ".json":
            return self._extract_json(path, effective_max_chars)
        elif suffix in {".csv", ".tsv"}:
            return self._extract_delimited(
                path, effective_max_chars, delimiter="\t" if suffix == ".tsv" else ","
            )
        elif suffix == ".docx":
            return self._extract_docx(path, effective_max_chars)
        elif suffix == ".xlsx":
            return self._extract_xlsx(path, effective_max_chars)
        elif suffix == ".pptx":
            return self._extract_pptx(path, effective_max_chars, effective_max_pages)
        elif suffix == ".pdf":
            return self._extract_pdf(path, effective_max_chars, effective_max_pages)
        else:
            raise DocumentExtractionError(f"Unsupported document format: '{suffix}'")

    def _extract_plain_text(self, path: Path, max_chars: int) -> ExtractedDocument:
        raw_bytes = path.read_bytes()
        text = self._decode_bytes(raw_bytes)
        return self._build_result(path, path.suffix.lstrip("."), text, max_chars)

    def _extract_json(self, path: Path, max_chars: int) -> ExtractedDocument:
        raw_bytes = path.read_bytes()
        text = self._decode_bytes(raw_bytes)
        try:
            parsed = json.loads(text)
            pretty_text = json.dumps(parsed, indent=2, ensure_ascii=False)
            res = self._build_result(path, "json", pretty_text, max_chars)
            if isinstance(parsed, dict):
                res.metadata["keys_count"] = len(parsed)
            elif isinstance(parsed, list):
                res.metadata["items_count"] = len(parsed)
            return res
        except json.JSONDecodeError:
            return self._build_result(path, "json", text, max_chars)

    def _extract_delimited(
        self, path: Path, max_chars: int, delimiter: str = ","
    ) -> ExtractedDocument:
        raw_bytes = path.read_bytes()
        text = self._decode_bytes(raw_bytes)
        try:
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            rows = list(reader)
            row_count = len(rows)
            col_count = max((len(r) for r in rows), default=0)
            res = self._build_result(path, "csv" if delimiter == "," else "tsv", text, max_chars)
            res.metadata["rows"] = row_count
            res.metadata["columns"] = col_count
            return res
        except Exception:
            return self._build_result(path, "csv", text, max_chars)

    def _extract_docx(self, path: Path, max_chars: int) -> ExtractedDocument:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if "word/document.xml" not in zf.namelist():
                    raise DocumentExtractionError("Invalid DOCX: missing word/document.xml")
                xml_content = zf.read("word/document.xml")
                tree = ET.fromstring(xml_content)
                namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

                paragraphs: list[str] = []
                for p_elem in tree.findall(".//w:p", namespaces):
                    texts = [
                        t_elem.text
                        for t_elem in p_elem.findall(".//w:t", namespaces)
                        if t_elem.text
                    ]
                    if texts:
                        paragraphs.append("".join(texts))

                extracted_text = "\n\n".join(paragraphs)
                res = self._build_result(path, "docx", extracted_text, max_chars)
                res.metadata["paragraph_count"] = len(paragraphs)
                return res
        except zipfile.BadZipFile as exc:
            raise DocumentExtractionError(f"Corrupted or invalid DOCX archive: {exc}") from exc
        except Exception as exc:
            raise DocumentExtractionError(f"Failed to extract DOCX: {exc}") from exc

    def _extract_xlsx(self, path: Path, max_chars: int) -> ExtractedDocument:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                namelist = set(zf.namelist())
                # 1. Parse shared strings table if present
                shared_strings: list[str] = []
                if "xl/sharedStrings.xml" in namelist:
                    ss_tree = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                    ns_main = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for si in ss_tree.findall(".//x:si", ns_main):
                        texts = [t.text for t in si.findall(".//x:t", ns_main) if t.text]
                        shared_strings.append("".join(texts))

                # 2. Find sheets
                sheet_files = [
                    f
                    for f in namelist
                    if f.startswith("xl/worksheets/sheet") and f.endswith(".xml")
                ]
                sheet_files.sort()

                sheet_texts: list[str] = []
                for sheet_file in sheet_files:
                    sheet_name = Path(sheet_file).stem
                    s_tree = ET.fromstring(zf.read(sheet_file))
                    ns_main = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

                    rows_data: list[str] = []
                    for row in s_tree.findall(".//x:row", ns_main):
                        row_vals: list[str] = []
                        for cell in row.findall(".//x:c", ns_main):
                            c_type = cell.attrib.get("t", "")
                            v_elem = cell.find("x:v", ns_main)
                            if v_elem is not None and v_elem.text:
                                val = v_elem.text
                                if c_type == "s" and val.isdigit():
                                    idx = int(val)
                                    val_str = (
                                        shared_strings[idx] if idx < len(shared_strings) else val
                                    )
                                else:
                                    val_str = val
                                row_vals.append(val_str)
                            else:
                                # Inline string
                                is_elem = cell.find("x:is", ns_main)
                                if is_elem is not None:
                                    t_elem = is_elem.find("x:t", ns_main)
                                    if t_elem is not None and t_elem.text:
                                        row_vals.append(t_elem.text)
                        if row_vals:
                            rows_data.append(" | ".join(row_vals))

                    if rows_data:
                        sheet_texts.append(f"--- Sheet: {sheet_name} ---\n" + "\n".join(rows_data))

                combined = "\n\n".join(sheet_texts)
                res = self._build_result(path, "xlsx", combined, max_chars)
                res.sheet_count = len(sheet_files)
                res.metadata["sheets"] = [Path(f).stem for f in sheet_files]
                return res
        except zipfile.BadZipFile as exc:
            raise DocumentExtractionError(f"Corrupted or invalid XLSX archive: {exc}") from exc
        except Exception as exc:
            raise DocumentExtractionError(f"Failed to extract XLSX: {exc}") from exc

    def _extract_pptx(self, path: Path, max_chars: int, max_pages: int) -> ExtractedDocument:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                namelist = set(zf.namelist())
                slide_files = [
                    f for f in namelist if f.startswith("ppt/slides/slide") and f.endswith(".xml")
                ]

                # Sort numerically by slide number: ppt/slides/slide1.xml -> 1
                def _slide_num(name: str) -> int:
                    m = re.search(r"slide(\d+)\.xml", name)
                    return int(m.group(1)) if m else 9999

                slide_files.sort(key=_slide_num)

                ns_draw = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                slides_output: list[str] = []
                total_slides = len(slide_files)

                for idx, slide_file in enumerate(slide_files[:max_pages], start=1):
                    s_tree = ET.fromstring(zf.read(slide_file))
                    slide_texts: list[str] = []
                    for t_elem in s_tree.findall(".//a:t", ns_draw):
                        if t_elem.text and t_elem.text.strip():
                            slide_texts.append(t_elem.text.strip())

                    body = "\n".join(slide_texts) if slide_texts else "(empty slide)"
                    slides_output.append(f"--- Slide {idx} ---\n{body}")

                combined = "\n\n".join(slides_output)
                res = self._build_result(path, "pptx", combined, max_chars)
                res.page_count = total_slides
                res.metadata["total_slides"] = total_slides
                res.metadata["extracted_slides"] = min(total_slides, max_pages)
                return res
        except zipfile.BadZipFile as exc:
            raise DocumentExtractionError(f"Corrupted or invalid PPTX archive: {exc}") from exc
        except Exception as exc:
            raise DocumentExtractionError(f"Failed to extract PPTX: {exc}") from exc

    def _extract_pdf(self, path: Path, max_chars: int, max_pages: int) -> ExtractedDocument:
        # First attempt: PySide6.QtPdf
        try:
            from PySide6.QtPdf import QPdfDocument

            doc = QPdfDocument()
            doc.load(str(path))
            # QPdfDocument load returns Error enum or None depending on version
            page_count = doc.pageCount()
            if page_count > 0:
                pages_text: list[str] = []
                limit_pages = min(page_count, max_pages)
                for page_idx in range(limit_pages):
                    selection = doc.getAllText(page_idx)
                    text = selection.text() if hasattr(selection, "text") else str(selection)
                    if text.strip():
                        pages_text.append(f"--- Page {page_idx + 1} ---\n{text.strip()}")

                doc.close()
                combined = "\n\n".join(pages_text)
                res = self._build_result(path, "pdf", combined, max_chars)
                res.page_count = page_count
                res.metadata["total_pages"] = page_count
                res.metadata["extracted_pages"] = limit_pages
                return res
        except Exception as qt_exc:
            logger.debug(f"QtPdf extraction attempted and fell back: {qt_exc}")

        # Fallback: pure-Python basic stream text extractor
        try:
            text = self._extract_pdf_raw_streams(path, max_pages)
            res = self._build_result(path, "pdf", text, max_chars)
            return res
        except Exception as exc:
            raise DocumentExtractionError(f"Failed to parse PDF document: {exc}") from exc

    def _extract_pdf_raw_streams(self, path: Path, max_pages: int) -> str:
        """Lightweight regex stream parser for basic unencrypted PDFs."""
        raw_bytes = path.read_bytes()
        if b"%PDF-" not in raw_bytes[:1024]:
            raise DocumentExtractionError("Not a valid PDF file (missing %PDF header)")

        # Check encryption
        if b"/Encrypt" in raw_bytes:
            raise DocumentExtractionError(
                "Password-protected or encrypted PDF cannot be extracted without credentials."
            )

        # Search for text streams
        import zlib

        stream_matches = list(
            re.finditer(b"stream[\r\n]+(.*?)[\r\n]+endstream", raw_bytes, re.DOTALL)
        )
        extracted_strings: list[str] = []
        pages_found = 0

        for match in stream_matches:
            data = match.group(1)
            # Try decompressing flate stream
            decompressed = None
            try:
                decompressed = zlib.decompress(data)
            except Exception:
                decompressed = data

            if decompressed:
                # Look for TJ or Tj operators: (text) Tj or [(t) 10 (ext)] TJ
                t_matches = re.findall(rb"\((.*?)\)\s*Tj", decompressed)
                for tm in t_matches:
                    with contextlib.suppress(Exception):
                        extracted_strings.append(tm.decode("latin-1"))

                if extracted_strings:
                    pages_found += 1
                    if pages_found >= max_pages:
                        break

        if not extracted_strings:
            return "(No extractable text found in PDF streams; document may be scanned image)"
        return " ".join(extracted_strings)

    def _decode_bytes(self, raw_bytes: bytes) -> str:
        """Decode bytes with robust fallback encodings."""
        for enc in ("utf-8", "utf-8-sig", "cp1256", "cp1252", "latin-1"):
            try:
                return raw_bytes.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="replace")

    def _build_result(
        self,
        path: Path,
        file_type: str,
        content: str,
        max_chars: int,
    ) -> ExtractedDocument:
        truncated = False
        final_content = content
        if len(final_content) > max_chars:
            final_content = final_content[:max_chars]
            truncated = True

        words = len(final_content.split())
        lines = len(final_content.splitlines())

        return ExtractedDocument(
            file_path=str(path),
            file_type=file_type,
            text_content=final_content,
            char_count=len(final_content),
            word_count=words,
            line_count=lines,
            truncated=truncated,
        )


_document_extractor_instance: DocumentExtractor | None = None


def get_document_extractor() -> DocumentExtractor:
    """Singleton getter for document extractor."""
    global _document_extractor_instance
    if _document_extractor_instance is None:
        _document_extractor_instance = DocumentExtractor()
    return _document_extractor_instance
