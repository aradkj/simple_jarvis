"""Unit tests for JARVIS File Intelligence & Universal Windows Application Discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.files.content_extractor import FileContentExtractor
from core.files.database import FileIndexDatabase
from core.files.discovery import FileDiscoveryService
from core.files.indexer import FileIndexer
from core.files.models import IndexedFile, IndexingScope
from core.files.search import FileSearchEngine
from tools.windows.discovery import WindowsApplicationDiscovery


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary mock file tree with Persian and English documents and code."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Text and markdown
    (ws / "resume.txt").write_text(
        "Experienced Python backend engineer with AI and NLP expertise.", encoding="utf-8"
    )
    (ws / "رزومه_فارسی.md").write_text(
        "مهندس نرم‌افزار با تخصص در سیستم‌های هوش مصنوعی و یادگیری عمیق.", encoding="utf-8"
    )
    (ws / "invoice_2026.csv").write_text(
        "Item,Quantity,Price\nServer Hosting,1,120\nDomain,2,30", encoding="utf-8"
    )

    # Code files
    (ws / "main.py").write_text(
        "import os\n\ndef run():\n    print('JARVIS Autonomous Agent')\n", encoding="utf-8"
    )
    (ws / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    # Subdirectory
    sub = ws / "projects" / "pc_shop"
    sub.mkdir(parents=True)
    (sub / "app.py").write_text("print('PC Shop eCommerce Platform')\n", encoding="utf-8")
    (sub / "README.md").write_text(
        "# PC Shop eCommerce\nProject documentation and setup.", encoding="utf-8"
    )

    # Excluded directory (should NOT be indexed)
    git_dir = ws / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("repositoryformatversion = 0", encoding="utf-8")

    node_modules = ws / "node_modules"
    node_modules.mkdir()
    (node_modules / "dummy.js").write_text("console.log('ignored');", encoding="utf-8")

    return ws


@pytest.fixture
def file_db(tmp_path: Path) -> FileIndexDatabase:
    db_file = tmp_path / "test_index.db"
    return FileIndexDatabase(db_path=db_file)


class TestFileDatabaseAndFTS5:
    """Test SQLite FTS5 database operations, indexing, and full-text searches."""

    def test_schema_creation(self, file_db: FileIndexDatabase):
        assert file_db.db_path.exists()
        stats = file_db.get_stats()
        assert stats.total_files == 0

    def test_batch_upsert_and_fts_search(self, file_db: FileIndexDatabase):
        file1 = IndexedFile(
            path="C:/test/resume.md",
            filename="resume.md",
            extension=".md",
            size_bytes=1024,
            mtime=1700000000.0,
            ctime=1700000000.0,
            is_binary=False,
            content_excerpt="Senior Python AI engineer resume with DeepMind tools experience.",
            char_count=65,
            indexed_at=1700000001.0,
        )
        file2 = IndexedFile(
            path="C:/test/رزومه_محمد.txt",
            filename="رزومه_محمد.txt",
            extension=".txt",
            size_bytes=2048,
            mtime=1700000005.0,
            ctime=1700000005.0,
            is_binary=False,
            content_excerpt="رزومه کاری برنامه‌نویس ارشد پایتون و هوش مصنوعی در ایران.",
            char_count=60,
            indexed_at=1700000006.0,
        )

        file_db.batch_upsert([file1, file2])
        stats = file_db.get_stats()
        assert stats.total_files == 2

        # English FTS search
        res_en = file_db.search_fts("engineer")
        assert len(res_en) >= 1
        assert "resume.md" in res_en[0].filename

        # Persian FTS search
        res_fa = file_db.search_fts("رزومه")
        assert len(res_fa) >= 1
        assert "رزومه_محمد.txt" in res_fa[0].filename

    def test_remove_missing_paths(self, file_db: FileIndexDatabase):
        f = IndexedFile(
            path="C:/test/file_a.txt",
            filename="file_a.txt",
            extension=".txt",
            size_bytes=100,
            mtime=1.0,
            ctime=1.0,
            content_excerpt="test content",
        )
        file_db.upsert_file(f)
        assert file_db.get_stats().total_files == 1

        # File is no longer in valid_paths set
        removed = file_db.remove_missing_paths(set())
        assert removed == 1
        assert file_db.get_stats().total_files == 0


class TestFileContentExtractor:
    """Test safe extraction of text, code, and binary detection."""

    def test_text_and_code_extraction(self, temp_workspace: Path):
        extractor = FileContentExtractor(max_excerpt_chars=500)
        calc_py = temp_workspace / "calculator.py"

        text, is_bin = extractor.extract_excerpt(calc_py)
        assert not is_bin
        assert "def add(a, b):" in text

    def test_binary_detection(self, tmp_path: Path):
        extractor = FileContentExtractor()
        bin_file = tmp_path / "sample.bin"
        bin_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe\x00\x00\x00")

        assert extractor.is_binary_file(bin_file)
        text, is_bin = extractor.extract_excerpt(bin_file)
        assert is_bin
        assert text == ""


class TestFileDiscoveryAndIndexing:
    """Test recursive file tree scanning and incremental indexing with exclusion boundaries."""

    def test_discovery_exclusions(self, temp_workspace: Path):
        scope = IndexingScope(root_paths=[str(temp_workspace)])
        discovery = FileDiscoveryService(scope=scope)

        found_paths = [str(p) for p in discovery.scan_files()]
        # Legitimate files must be present
        assert any("resume.txt" in p for p in found_paths)
        assert any("calculator.py" in p for p in found_paths)
        assert any("pc_shop" in p for p in found_paths)

        # Excluded directories must NOT be present
        assert not any(".git" in p for p in found_paths)
        assert not any("node_modules" in p for p in found_paths)

    def test_incremental_indexing(self, temp_workspace: Path, file_db: FileIndexDatabase):
        scope = IndexingScope(root_paths=[str(temp_workspace)])
        discovery = FileDiscoveryService(scope=scope)
        indexer = FileIndexer(db=file_db, discovery=discovery)

        # First pass: index all files
        count1 = indexer.run_sync_index()
        assert count1 >= 5

        stats1 = file_db.get_stats()
        assert stats1.total_files == count1

        # Second pass without modifications: 0 files updated (incremental optimization)
        count2 = indexer.run_sync_index()
        assert count2 == 0


class TestFileSearchEngineBilingual:
    """Test bilingual Persian and English search queries, extension detection, and ranking."""

    def test_query_parsing(self, file_db: FileIndexDatabase):
        engine = FileSearchEngine(db=file_db)

        # Persian query with extension
        terms, ext = engine.parse_query("فایل‌های پی دی اف پروژه را بیار")
        assert ext == ".pdf"
        assert "پروژه" in terms

        # English query with extension
        terms_en, ext_en = engine.parse_query("find python files for calculator")
        assert ext_en == ".py"
        assert "calculator" in terms_en

    def test_bilingual_search(self, temp_workspace: Path, file_db: FileIndexDatabase):
        scope = IndexingScope(root_paths=[str(temp_workspace)])
        indexer = FileIndexer(db=file_db, discovery=FileDiscoveryService(scope=scope))
        indexer.run_sync_index()

        engine = FileSearchEngine(db=file_db)

        # 1. Search in English for resume
        res1 = engine.search("resume")
        assert len(res1) >= 1
        assert any("resume.txt" in r.filename for r in res1)

        # 2. Search in Persian for resume («رزومه‌ام کجاست»)
        res2 = engine.search("رزومه‌ام کجاست")
        assert len(res2) >= 1
        assert any("رزومه" in r.filename or "resume" in r.filename for r in res2)

        # 3. Search for project («پروژه پیسی شاپ» or "pc shop")
        res3 = engine.search("pc shop")
        assert len(res3) >= 1
        assert any("pc_shop" in r.path for r in res3)


class TestUniversalWindowsApplicationDiscovery:
    """Test universal application discovery, Persian alias resolution, and fuzzy matching."""

    def test_builtin_discovery(self):
        discovery = WindowsApplicationDiscovery()
        apps = discovery.scan_applications()
        assert len(apps) >= 5

        # Standard apps exist
        assert "notepad" in apps or "calc" in apps

    def test_persian_alias_resolution(self):
        discovery = WindowsApplicationDiscovery()
        discovery.scan_applications()

        # Persian queries
        found_calc = discovery.find_application("ماشین حساب")
        assert found_calc is not None
        assert found_calc.app_id in ("calc", "calculator")

        found_term = discovery.find_application("ترمینال")
        assert found_term is not None
        assert found_term.app_id in ("wt", "terminal")

        found_edge = discovery.find_application("ادج")
        assert found_edge is not None
        assert "edge" in found_edge.app_id or "msedge" in found_edge.app_id

        found_code = discovery.find_application("وی اس کد")
        assert found_code is not None
        assert "code" in found_code.app_id or "visualstudiocode" in found_code.app_id

    def test_fuzzy_matching(self):
        discovery = WindowsApplicationDiscovery()
        discovery.scan_applications()

        # Slight typo: 'chrume' -> Chrome
        found = discovery.find_application("chrume")
        if found:
            assert "chrome" in found.app_id.lower() or "chrome" in found.name.lower()
