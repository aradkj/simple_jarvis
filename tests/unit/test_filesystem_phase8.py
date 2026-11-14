"""Unit tests for Phase 8 File System Agent and Document Extraction."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from core.execution_context import ExecutionContext
from tools.base import ToolExecutionStatus
from tools.filesystem.document_extractor import (
    DocumentExtractionError,
    DocumentExtractor,
)
from tools.filesystem.file_service import FileService
from tools.filesystem.file_tools import (
    FileDeleteInput,
    FileDeleteTool,
    FileDocumentExtractInput,
    FileDocumentExtractTool,
    FileEditTextInput,
    FileEditTextTool,
    FileWriteTextInput,
    FileWriteTextTool,
)
from tools.filesystem.path_security import get_path_security_service


@pytest.fixture
def auth_temp_dir(tmp_path: Path):
    """Fixture providing a temporary directory registered as an authorized directory."""
    sec = get_path_security_service()
    entry = sec.add_directory(str(tmp_path), display_name="TestAuthDir")
    yield tmp_path
    sec.revoke_directory(entry.directory_id)


class TestDocumentExtractor:
    """Tests for multi-format document extraction engine."""

    def test_plain_text_and_markdown(self, tmp_path: Path):
        extractor = DocumentExtractor()
        txt_file = tmp_path / "sample.txt"
        txt_file.write_text("Hello world\nSecond line of document", encoding="utf-8")

        res = extractor.extract(txt_file)
        assert res.file_type == "txt"
        assert "Hello world" in res.text_content
        assert res.word_count == 6
        assert res.line_count == 2
        assert not res.truncated

    def test_json_extraction_pretty_and_metadata(self, tmp_path: Path):
        extractor = DocumentExtractor()
        json_file = tmp_path / "data.json"
        json_file.write_text('{"name": "JARVIS", "version": "0.8.0", "phase": 8}', encoding="utf-8")

        res = extractor.extract(json_file)
        assert res.file_type == "json"
        assert '"version": "0.8.0"' in res.text_content
        assert res.metadata.get("keys_count") == 3

    def test_csv_extraction_with_rows_and_cols(self, tmp_path: Path):
        extractor = DocumentExtractor()
        csv_file = tmp_path / "table.csv"
        csv_file.write_text("id,name,role\n1,Alice,Engineer\n2,Bob,Architect\n", encoding="utf-8")

        res = extractor.extract(csv_file)
        assert res.file_type == "csv"
        assert "Alice" in res.text_content
        assert res.metadata.get("rows") == 3
        assert res.metadata.get("columns") == 3

    def test_docx_extraction(self, tmp_path: Path):
        extractor = DocumentExtractor()
        docx_file = tmp_path / "test.docx"

        # Build mock valid DOCX zip archive
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>First Paragraph</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Second Paragraph with Details</w:t></w:r></w:p>"
            "</w:body></w:document>"
        )
        with zipfile.ZipFile(docx_file, "w") as zf:
            zf.writestr("word/document.xml", doc_xml)

        res = extractor.extract(docx_file)
        assert res.file_type == "docx"
        assert "First Paragraph" in res.text_content
        assert "Second Paragraph with Details" in res.text_content
        assert res.metadata.get("paragraph_count") == 2

    def test_xlsx_extraction(self, tmp_path: Path):
        extractor = DocumentExtractor()
        xlsx_file = tmp_path / "test.xlsx"

        ss_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<si><t>Project</t></si>"
            "<si><t>JARVIS</t></si>"
            "</sst>"
        )
        sheet_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>"
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            "</sheetData></worksheet>"
        )
        with zipfile.ZipFile(xlsx_file, "w") as zf:
            zf.writestr("xl/sharedStrings.xml", ss_xml)
            zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)

        res = extractor.extract(xlsx_file)
        assert res.file_type == "xlsx"
        assert "Project | JARVIS" in res.text_content
        assert res.sheet_count == 1

    def test_pptx_extraction(self, tmp_path: Path):
        extractor = DocumentExtractor()
        pptx_file = tmp_path / "slides.pptx"

        slide1_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            "<p:cSld><p:spTree><p:sp><p:txBody>"
            "<a:p><a:r><a:t>Title: Phase 8 Architecture</a:t></a:r></a:p>"
            "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
        )
        with zipfile.ZipFile(pptx_file, "w") as zf:
            zf.writestr("ppt/slides/slide1.xml", slide1_xml)

        res = extractor.extract(pptx_file)
        assert res.file_type == "pptx"
        assert "Title: Phase 8 Architecture" in res.text_content
        assert res.page_count == 1

    def test_max_chars_bounding(self, tmp_path: Path):
        extractor = DocumentExtractor()
        big_file = tmp_path / "big.txt"
        big_file.write_text("A" * 5000, encoding="utf-8")

        res = extractor.extract(big_file, max_chars=100)
        assert len(res.text_content) == 100
        assert res.truncated is True

    def test_unsupported_format_raises_error(self, tmp_path: Path):
        extractor = DocumentExtractor()
        bin_file = tmp_path / "file.unknown_xyz"
        bin_file.write_bytes(b"\x00\x01\x02\x03")

        with pytest.raises(DocumentExtractionError):
            extractor.extract(bin_file)


class TestFileOperationsService:
    """Tests for FileService operations."""

    def test_atomic_write_text(self, auth_temp_dir: Path):
        svc = FileService()
        target = auth_temp_dir / "created.txt"
        res = svc.write_text(str(target), "Initial text", overwrite=False)
        assert res.success is True
        assert target.read_text(encoding="utf-8") == "Initial text"

        # Overwrite=False failure
        res2 = svc.write_text(str(target), "New text", overwrite=False)
        assert res2.success is False
        assert "already exists" in res2.message

        # Overwrite=True success
        res3 = svc.write_text(str(target), "Overwritten text", overwrite=True)
        assert res3.success is True
        assert target.read_text(encoding="utf-8") == "Overwritten text"

    def test_windows_reserved_device_names_rejected(self, auth_temp_dir: Path):
        svc = FileService()
        con_target = auth_temp_dir / "con.txt"
        res = svc.write_text(str(con_target), "data")
        assert res.success is False
        assert "reserved Windows device name" in res.message

    def test_edit_text_replace_and_diff(self, auth_temp_dir: Path):
        svc = FileService()
        target = auth_temp_dir / "code.py"
        target.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

        res = svc.edit_text(
            str(target),
            target_string="'world'",
            replacement_string="'JARVIS'",
        )
        assert res.success is True
        assert "JARVIS" in target.read_text(encoding="utf-8")
        assert "diff" in res.details
        assert "-    return 'world'" in res.details["diff"]
        assert "+    return 'JARVIS'" in res.details["diff"]

    def test_copy_and_move_file(self, auth_temp_dir: Path):
        svc = FileService()
        src = auth_temp_dir / "source.txt"
        src.write_text("Copy me", encoding="utf-8")
        dst_copy = auth_temp_dir / "copied.txt"
        dst_move = auth_temp_dir / "moved.txt"

        # Copy
        res_copy = svc.copy_file(str(src), str(dst_copy))
        assert res_copy.success is True
        assert dst_copy.exists() and src.exists()

        # Move
        res_move = svc.move_file(str(src), str(dst_move))
        assert res_move.success is True
        assert dst_move.exists() and not src.exists()

    def test_compare_diff(self, auth_temp_dir: Path):
        svc = FileService()
        fa = auth_temp_dir / "a.txt"
        fb = auth_temp_dir / "b.txt"
        fa.write_text("line1\nline2\n", encoding="utf-8")
        fb.write_text("line1\nline2_modified\n", encoding="utf-8")

        res = svc.compare_diff(str(fa), str(fb))
        assert res.success is True
        assert res.details["identical"] is False
        assert "+line2_modified" in res.details["diff"]

    def test_find_duplicates(self, auth_temp_dir: Path):
        svc = FileService()
        sub = auth_temp_dir / "subdir"
        sub.mkdir()
        f1 = auth_temp_dir / "orig.txt"
        f2 = sub / "dup.txt"
        f3 = auth_temp_dir / "unique.txt"

        f1.write_text("Exact duplicate content across files", encoding="utf-8")
        f2.write_text("Exact duplicate content across files", encoding="utf-8")
        f3.write_text("Completely unique content", encoding="utf-8")

        res = svc.find_duplicates(str(auth_temp_dir))
        assert res.success is True
        assert res.details["duplicate_groups_count"] == 1
        assert res.details["total_duplicate_files"] == 2

    def test_archive_create_inspect_extract(self, auth_temp_dir: Path):
        svc = FileService()
        doc = auth_temp_dir / "doc.txt"
        doc.write_text("Content to be archived in zip file", encoding="utf-8")

        zip_p = auth_temp_dir / "test_out.zip"
        res_create = svc.create_archive(str(zip_p), [str(doc)])
        assert res_create.success is True
        assert zip_p.exists()

        res_insp = svc.inspect_archive(str(zip_p))
        assert res_insp.success is True
        assert res_insp.details["entries_count"] == 1

        extract_dir = auth_temp_dir / "extracted"
        res_extr = svc.extract_archive(str(zip_p), str(extract_dir))
        assert res_extr.success is True
        assert (extract_dir / "doc.txt").exists()
        assert (extract_dir / "doc.txt").read_text(
            encoding="utf-8"
        ) == "Content to be archived in zip file"

    def test_zip_slip_defense(self, auth_temp_dir: Path):
        svc = FileService()
        malicious_zip = auth_temp_dir / "evil.zip"
        with zipfile.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("../../evil.txt", "traversal attempt")

        extract_dir = auth_temp_dir / "safe_extract"
        res = svc.extract_archive(str(malicious_zip), str(extract_dir))
        assert res.success is False
        assert "Zip Slip attack detected" in res.message


class TestFileToolsExecution:
    """Tests executing Phase 8 tools through Tool definitions with ExecutionContext."""

    def test_file_extract_document_tool(self, auth_temp_dir: Path):
        tool = FileDocumentExtractTool()
        f = auth_temp_dir / "notes.md"
        f.write_text("# Title\n- Bullet 1\n- Bullet 2\n", encoding="utf-8")

        ctx = ExecutionContext()
        res = tool.execute(FileDocumentExtractInput(file_path=str(f)), ctx)
        assert res.status == ToolExecutionStatus.SUCCESS
        assert "Bullet 1" in res.data["text_content"]

    def test_file_write_and_edit_tool(self, auth_temp_dir: Path):
        w_tool = FileWriteTextTool()
        e_tool = FileEditTextTool()
        ctx = ExecutionContext()

        f = auth_temp_dir / "module.py"
        res1 = w_tool.execute(FileWriteTextInput(file_path=str(f), content="x = 10\n"), ctx)
        assert res1.status == ToolExecutionStatus.SUCCESS

        res2 = e_tool.execute(
            FileEditTextInput(file_path=str(f), target_string="10", replacement_string="20"), ctx
        )
        assert res2.status == ToolExecutionStatus.SUCCESS
        assert "x = 20" in f.read_text(encoding="utf-8")

    def test_file_delete_permanent(self, auth_temp_dir: Path):
        del_tool = FileDeleteTool()
        ctx = ExecutionContext()
        f = auth_temp_dir / "to_delete.txt"
        f.write_text("delete me", encoding="utf-8")

        res = del_tool.execute(FileDeleteInput(file_path=str(f), permanent=True), ctx)
        assert res.status == ToolExecutionStatus.SUCCESS
        assert not f.exists()
