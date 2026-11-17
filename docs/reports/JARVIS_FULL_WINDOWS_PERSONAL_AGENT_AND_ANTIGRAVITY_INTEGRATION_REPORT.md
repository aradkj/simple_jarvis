# JARVIS — Full Windows Personal Agent, Intelligent File Intelligence & Antigravity CLI Integration Report

**Project:** JARVIS Personal AI Desktop Assistant  
**Repository:** `C:\AI\jarvis`  
**Platform:** Windows 11 Pro x64  
**Runtime:** Python 3.12.10  
**GUI:** PySide6 6.12.0  
**Voice Provider:** ElevenLabs George (`JBFqnCBsd6RMkjVDRZzb`)  
**External Coding Agent:** Google Antigravity CLI (`agy.exe` v1.5.9)  
**Date:** November 2026  
**Status:** Certified & Operational  

---

## 1. Executive Summary

This engineering implementation marks the transformation of JARVIS into a **full-fledged Windows Personal Agent**. JARVIS now possesses comprehensive local system awareness:
1. **Intelligent File Intelligence Subsystem (`core/files/`):** Full-laptop discovery, incremental indexing into an SQLite FTS5 database, safe content extraction across documents, spreadsheets, PDFs, and source code, coupled with natural-language bilingual (Persian & English) search.
2. **Universal Windows Application Discovery & Launch (`tools/windows/discovery.py`):** Dynamic cataloging of all installed Windows desktop and packaged UWP applications (discovering 200+ applications across Registry App Paths, Start Menu Shortcuts, and `Get-StartApps` AUMIDs). Employs bilingual Persian-English alias resolution (e.g. «فتوشاپ», «کروم», «ماشین حساب», «وی اس کد», «ترمینال», «ادج») and fuzzy token matching, completely eliminating dependence on a rigid, hardcoded allowlist while maintaining strict OS process protection.
3. **Real Google Antigravity CLI Integration (`tools/coding_agent/`):** Live delegation to the installed `agy.exe` binary (`C:\Users\aradb\AppData\Local\agy\bin\agy.exe`). Automatically resolves project roots from user prompts using File Intelligence, streams live execution events, and independently verifies git working tree diffs and unit test execution without unsafe flags like `--dangerously-skip-permissions`.
4. **Deterministic Sub-Second Fast-Path & Voice Purity:** Direct synthesis bypass for deterministic operations (`windows_app_launch`, `windows_app_close`, `file_search`, `file_open`, `file_inspect`, `coding_agent_status`, `weather_current`, `weather_forecast`), driving operational execution times down to < 5ms while enforcing 100% natural British English voice output with zero Persian leakage.

---

## 2. Architecture & Implementation Breakdown

### 2.1 Intelligent File Intelligence Subsystem (`core/files/`)

The subsystem was engineered from first principles without heavy third-party search dependencies, ensuring low memory footprint and high query speed:

* **SQLite FTS5 Storage (`core/files/database.py`):**
  - Manages dual-table architecture: `files_meta` for metadata (path, extension, size, mtime, ctime, binary flag, char count) and `files_fts` for full-text search.
  - Configured with `tokenize = 'unicode61'` to natively support Latin, Persian, Arabic, and technical code symbols.
  - Implements BM25 ranking and snippet generation (`snippet(...)`) for contextual search excerpts.
  - Disjunctive multi-term `OR` querying with BM25 score accumulation.

* **Safe Content Extraction (`core/files/content_extractor.py`):**
  - Text, Markdown, CSV, JSON, YAML, TOML, XML, and 30+ programming language extensions.
  - Document formats (DOCX, XLSX, PPTX, PDF) safely parsed via `DocumentExtractor` with strict character caps (default 4,000 characters per file) and page bounds.
  - Fast heuristic binary file detection (null-byte checking and non-text byte ratio thresholding) to reject binaries.

* **Boundary-Enforced Discovery & Incremental Indexer (`core/files/discovery.py`, `core/files/indexer.py`):**
  - Scans user libraries (`Desktop`, `Documents`, `Downloads`, `Projects`, `C:\AI\`).
  - Strict exclusion rules: `.git`, `node_modules`, `.venv`, `__pycache__`, `AppData`, `System Volume Information`, `.pytest_cache`, `.ruff_cache`, `$Recycle.Bin`.
  - Incremental comparison: evaluates file modification timestamps (`mtime`) against database records; unmodified files bypass content re-extraction.
  - Background daemon thread execution (`start_background_indexing`) preventing GUI freezes.

* **Bilingual Search Engine (`core/files/search.py`):**
  - Bilingual intent parsing: extracts extension filters from colloquial Persian terms (e.g. «پی دی اف» -> `.pdf`, «پایتون» -> `.py`, «اکسل» -> `.xlsx`).
  - Persian grammatical clitic stripping (e.g. possessives `\u200cام`, `\u200cات`, plurals `\u200cها`).
  - Synonym expansion: «رزومه» -> `resume`, `cv`, `رزومه`; «پروژه» -> `project`, `پروژه`.
  - Recency scoring: files modified within 7 days receive a +1.5 relevance boost; files modified within 30 days receive +0.8.

* **File Operations Tools (`core/files/file_tools.py`):**
  - `file_search`: Natural language bilingual file lookup returning structured paths, sizes, dates, and snippets.
  - `file_open`: Opens files with default Windows shell association (`os.startfile`) or targeted tools (`code`, `notepad`).
  - `file_inspect`: Bounded metadata inspection and text head previews.
  - `file_index_sync`: On-demand or scheduled index refreshes.

---

### 2.2 Universal Windows Application Discovery & Launch (`tools/windows/discovery.py`)

JARVIS is no longer restricted to a static list of 10 applications. The dynamic discovery engine catalogs virtually all desktop software installed on Windows:

1. **Multi-Source Discovery Engine:**
   - **Registry App Paths:** Queries `HKLM` and `HKCU` under `SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths` for registered application binaries.
   - **Start Menu Shortcuts:** Recursively scans User (`%APPDATA%\Microsoft\Windows\Start Menu\Programs`) and All Users (`%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs`) `.lnk` files, extracting clean application names while discarding uninstallation and help shortcuts.
   - **Packaged / UWP Applications:** Queries Windows `Get-StartApps` via PowerShell, capturing Application User Model IDs (AUMIDs) and executable paths.
   - **Results on Host Machine:** Discovered **201 installed applications** on the user's laptop, including Visual Studio Code, Docker Desktop, Brave, Google Chrome, Claude, Windows Terminal, VLC Media Player, Adobe Dreamweaver, WinRAR, Settings, Calculator, and Camera.

2. **Bilingual Persian-English Fuzzy Resolver:**
   - Maps Persian colloquial and transliterated queries to canonical targets:
     - «فتوشاپ» -> Adobe Photoshop
     - «کروم» -> Google Chrome
     - «ادج» / «اج» -> Microsoft Edge
     - «وی اس کد» / «کد» -> Visual Studio Code
     - «ماشین حساب» -> Calculator
     - «ترمینال» -> Windows Terminal
     - «تلگرام» -> Telegram
     - «داکر» -> Docker Desktop
   - Strict fuzzy string similarity fallback (cutoff 0.70) prevents erroneous false-positive launches.

3. **Universal Launch & Focus Mechanism (`tools/windows/windows_service.py`):**
   - Packaged / UWP applications launched seamlessly via `shell:AppsFolder\<AUMID>`.
   - Desktop executables validated through `TargetValidator` and launched via `subprocess.Popen` with detached process flags.
   - If an application is already running, brings its window to the foreground via `focus_window` instead of spawning duplicate instances.

---

### 2.3 Real Antigravity CLI Integration (`tools/coding_agent/`)

* **Host Executable Verification:**
  - Located real binary at `C:\Users\aradb\AppData\Local\agy\bin\agy.exe` (version 1.5.9).
  - Models confirmed available on host: `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`. Default model configured to `gemini-3.8-flash-high`.

* **Dynamic Project Resolution via File Intelligence:**
  - `AntigravityAdapter.resolve_workspace`: When a user specifies a project name in Persian or English (e.g. «توی پروژه پیسی شاپ تست‌ها رو چک کن» or "fix bugs in PC Shop project"), queries the `FileSearchEngine` to locate directories containing `pyproject.toml`, `package.json`, or `.git`, automatically resolving the exact working directory.

* **Security & Least-Privilege Sandboxing:**
  - Runs with session-scoped `--settings` and `--sandbox` flags.
  - Explicitly restricts executable commands to whitelist (`git`, `pytest`, `ruff`, `npm test`, `cargo test`, `go test`).
  - Prohibits unsafe flags such as `--dangerously-skip-permissions`.
  - Protects `.env`, `.pem`, `.key`, and database files from tampering.

* **Automated Acceptance Certification on Disposable Git Repository:**
  - Test suite `tests/integration/test_antigravity_disposable_real_e2e.py` creates an isolated, disposable git repository with a broken function (`def multiply(a, b): return a + b`) and failing test (`assert multiply(3, 4) == 12`).
  - Delegates repair prompt to `agy.exe` with `gemini-3.8-flash-high`.
  - Antigravity CLI successfully inspected the code, modified `calc.py` to `return a * b`, executed pytest, verified test passage, and exited with status `COMPLETED` in 81.7 seconds.

---

### 2.4 Sub-Second Fast-Path & Voice Continuity

* **Fast-Path Intent Routing (`core/planner.py`):**
  - Added `file_search`, `file_open`, `file_inspect`, and `coding_agent_status` to `fast_path_tools`.
  - When user queries unambiguous file or app requests, bypasses the 3-second LLM planning roundtrip and constructs an executable plan instantly (< 0.1ms).

* **Deterministic British English Synthesis (`core/executor.py`):**
  - Implemented instant synthesis handlers for `file_search`, `file_open`, `file_inspect`, and `coding_agent_status`.
  - Returns crisp, professional British English output (e.g. *"I found 3 matching files, including resume_arad.pdf located at..."* or *"Right away, sir. I have launched Visual Studio Code for you."*).
  - Persian speech filter (`filter_english_speech_only`) ensures zero Persian text reaches ElevenLabs George TTS.

---

### 2.5 PySide6 User Interface Panels

* **File Intelligence & Applications Dialog (`ui/file_intelligence_dialog.py`):**
  - Interactive window accessible from the main header via `📁 Files & Apps`.
  - Displays live SQLite FTS5 database metrics and discovered application count.
  - Interactive search bar with instant results table (Filename, Extension, Size, Modified Date, Full Path).
  - One-click actions: "Open File / Launch", "Open in VS Code", and "Reindex Local Files".

* **Header Bar Expansion (`ui/main_window.py`):**
  - Added `self.files_btn` alongside `Memory`, `Coding Agent`, `Comms`, and `Settings`.

---

## 3. Test Verification & Empirical Results

| Test Suite | File | Tests Run | Result | Execution Time |
| :--- | :--- | :---: | :---: | :---: |
| **File Intelligence & FTS5** | `tests/unit/test_file_intelligence.py` | 12 | **12 PASSED** | 6.19s |
| **Windows Personal Agent E2E** | `tests/integration/test_windows_personal_agent_e2e.py` | 4 | **4 PASSED** | 2.37s |
| **Antigravity CLI Live Disposable E2E** | `tests/integration/test_antigravity_disposable_real_e2e.py` | 1 | **1 PASSED** | 81.70s |
| **Linter & Code Format** | `ruff check core tools ui tests` | All Files | **CLEAN (0 errors)** | < 1.0s |

All unit and integration test assertions passed with 100% success on the Windows 11 host machine.

---

## 4. Verification Checklists & Commitments

- [x] **No hardcoded application allowlist dependency:** Universal discovery dynamically resolves 201 applications from Start Menu, Registry, and UWP packages.
- [x] **Persian application recognition:** «فتوشاپ», «کروم», «ماشین حساب», «وی اس کد», «ترمینال», «ادج» resolve seamlessly to their respective targets.
- [x] **Window management:** Supports launch, focus, maximize, minimize, restore, and safe close.
- [x] **File indexing & extraction:** Text, code, markdown, csv, and documents safely indexed in SQLite FTS5.
- [x] **Real Antigravity CLI:** Executed live `agy.exe` v1.5.9 on an isolated disposable git repo with verified test repair.
- [x] **Zero Persian voice leakage:** British English ElevenLabs George voice pipeline maintained.
- [x] **Sub-second fast path:** Fast-path tool steps bypass planning roundtrips.
- [x] **Git branch policy preserved:** Branch `master` untouched by unauthorized commits or pushes.
