# JARVIS — Personal AI Desktop Agent

JARVIS is a modular, production-oriented personal AI desktop assistant engineered specifically for **Windows 11** on Intel Core i5 / 16 GB RAM hardware. The agent leverages cloud-based **Google Gemini APIs** via the official `google-genai` SDK for reasoning, multi-turn conversations with incremental text streaming, and execution planning, coupled with a responsive native desktop UI built on **PySide6 (Qt 6)**.

---

## Supported Environment

- **Operating System:** Windows 11 (64-bit)
- **Target Hardware:** Intel Core i5-6300U CPU @ 2.40GHz / 16 GB RAM
- **Primary Language:** Python 3.12 x64
- **Desktop Framework:** PySide6 (Qt 6.12+)
- **Primary AI Provider:** Google Gemini via official `google-genai` SDK
- **Default AI Model:** `gemini-3.8-flash` (configurable to `gemini-2.5-flash`, `gemini-2.5-pro`, etc.)
- **Local AI Models:** Not required (cloud inference prevents CPU/RAM saturation)
- **Interface Support:** Dual Persian (فارسی / RTL) & English (LTR)

---

## Current Status: Phase 2, Phase 3, Phase 4 & Phase 5 — Complete

### Phase 2: Multi-Provider Core & Resilience
- [x] Full multi-provider support: Google Gemini, OpenAI, Anthropic Claude, DeepSeek, OpenRouter, and Groq
- [x] Dynamic `ModelCatalog` with lifecycle tracking (`active`, `preview`, `deprecated`, `retired`) and parameter adaptations
- [x] Intelligent automatic fallback across providers with strict 16-state cross-provider privacy enforcement
- [x] Responses API streaming protocol support with partial-text preservation on interrupted streams
- [x] Zero API key leakage into logs or SQLite storage; atomic, validated configuration management

### Phase 3: Agent Core & Planning
- [x] Deterministic 11-state machine (`AgentStateMachine`) with audit transition logging
- [x] Structured planning engine (`AgentPlanner`) with DAG dependency resolution and cycle prevention
- [x] Bounded execution loop (`AgentExecutor`) with loop detection, per-step retries, and task timeouts
- [x] Tool proposal architecture (`ToolProposal`) with human-in-the-loop approval gates for sensitive actions
- [x] Default-deny security policy enforced via `StrictDefaultDenyPermissionManager`
- [x] Deterministic mock tool suite (`MockSearchTool`, `MockCalculatorTool`, `MockWeatherTool`, `MockDangerousSystemTool`)
- [x] PySide6 `AgentExecutionWorker(QThread)` for non-blocking UI integration

### Phase 4: Real-World Tool Execution & Windows System Intelligence
- [x] Native Windows System Intelligence service (`tools/system/system_service.py`) via Win32 ctypes (zero external dependencies)
- [x] Real-world system tools: `system_get_cpu_info`, `system_get_memory_info`, `system_get_disk_info`, `system_get_network_info`, `system_get_overview`
- [x] Strict path containment and traversal defense (`tools/filesystem/path_security.py`) with user-authorized directory boundaries
- [x] Sensitive file denylist blocking `.env`, credentials, private keys, SSH/AWS directories, and browser profiles
- [x] Automated regex-based secret redaction for API keys, tokens, and passwords
- [x] Bounded real-world file inspection tools: `file_list_directory`, `file_get_metadata`, `file_read_text`, `file_search_text`
- [x] Windows reparse point, symbolic link, and directory junction detection & blocking
- [x] Handle-based TOCTOU protection (`safe_open_for_reading`) via Win32 `GetFinalPathNameByHandleW`
- [x] Cloud provider privacy boundary requiring explicit user confirmation with SHA-256 fingerprint binding
- [x] Untrusted file content sandboxing with anti-prompt-injection directives
- [x] Interactive UI directory authorization manager in Settings dialog (`QFileDialog.getExistingDirectory`)

### Phase 5: Persistent Memory System, Context Retrieval, User Memory Management & Privacy
- [x] Structured categorization: User Profile, Preferences, Project context, and Episodic memory
- [x] Explicit consent & controlled extraction ("Remember that...", "یادت باشه که...", "Save preference...", "Forget that...")
- [x] Additive SQLite storage with WAL journal mode and FTS5 full-text indexing + fallback
- [x] Deterministic multi-signal relevance ranking (lexical overlap, importance, exponential recency decay, confidence, project boost)
- [x] Bounded prompt context builder (`[RELEVANT USER MEMORY]`) with strict character budgets and untrusted data sandboxing
- [x] Lifecycle & conflict resolution: updating a preference automatically marks older conflicting records as superseded
- [x] Strict privacy boundaries: credentials, secrets, API keys, private keys, and credit cards are filtered out
- [x] Hardened cloud transmission boundary: separate storage consent from provider transmission consent with user-controlled toggle (`MEMORY_ALLOW_CLOUD_TRANSMISSION`, defaults to False)
- [x] Defense-in-depth ProviderManager scrubbing preventing untrusted memory leakage across cross-provider fallbacks
- [x] Zero-dependency baseline with extensible embedding provider interface (`NoOpEmbeddingProvider`)
- [x] PySide6 User Memory Management Dialog with search, category filtering, card approval/rejection, inline edit, cloud transmission toggle, and Persian RTL support

### Phase 6: Native Windows Control, Desktop Interaction & Secure System Actions
- [x] Native Windows Control subsystem (`tools/windows/`) with zero external dependencies (pure Win32 ctypes & Core Audio COM)
- [x] Application management: allowlist-based discovery, safe execution via `subprocess.Popen(shell=False)`, process enumeration via Toolhelp32 snapshot, and graceful `WM_CLOSE` termination
- [x] Desktop window management: top-level window enumeration via `EnumDesktopWindows`, focus/restore, minimize, maximize, and window closure
- [x] Windows Core Audio master volume inspection, scalar volume adjustment (0-100%), and mute/unmute control
- [x] Physical display brightness inspection and controls via DXVA2 API with graceful hardware capability reporting
- [x] Windows power status inspection (`GetSystemPowerStatus`) and safe workstation locking, sleep, restart, and shutdown
- [x] Protected target enforcement (`TargetValidator`) blocking OS subsystem binaries (`csrss.exe`, `lsass.exe`, `services.exe`, etc.) and shell surfaces (`Shell_TrayWnd`, `Progman`, etc.)
- [x] Strict two-step confirmation for destructive power operations (`windows_power_restart` and `windows_power_shutdown`) with unsaved work loss warnings, confirmation checkbox, and native confirmation prompt
- [x] Full ancestor reparse point traversal protection preventing directory junction and symlink redirection attacks
- [x] Anti-tampering PID reuse defense validating process creation time via `kernel32.GetProcessTimes`
- [x] Granular permission architecture across 11 Windows Control categories enforced via `StrictDefaultDenyPermissionManager`
- [x] Human approval lifecycle gating for high-risk and critical tools (`ApprovalManager`) with single-use, tamper-proof parameter binding
- [x] PySide6 Settings Dialog integration with granular permission toggles and real-time diagnostic status buttons
- [x] 335 automated regression tests passing with 100% success rate across all modules (34 Phase 6 specific unit and real Windows integration tests)
- [x] Certified: **PHASE 6 CLOSED — READY FOR PHASE 7**

---

## Installation & Setup

### 1. Prerequisites
Ensure Python 3.12 x64 and Git are installed on your Windows 11 system.

### 2. Clone / Open Repository
```powershell
cd C:\AI\jarvis
```

### 3. Create Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 4. Install Dependencies
```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Configuration Setup
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Open `.env` in an editor and configure your environment:
```env
APP_ENV=development
APP_NAME=JARVIS
DEBUG=true
LOG_LEVEL=INFO
APP_LANGUAGE=en

# Cloud Gemini API Key (Obtain from https://aistudio.google.com/)
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-3.8-flash
GEMINI_TEMPERATURE=0.7
GEMINI_MAX_OUTPUT_TOKENS=4096
GEMINI_REQUEST_TIMEOUT=30.0
CONVERSATION_HISTORY_LIMIT=20
```

*Note: You can also configure the API key and model directly inside the running application by clicking **⚙ System Settings**.*

---

## Running the Application

Launch the desktop assistant:
```powershell
python app.py
```
Or via virtual environment directly:
```powershell
.\.venv\Scripts\python app.py
```

### Testing the Gemini Connection
1. Launch the app and click **⚙ System Settings** on the bottom-left sidebar.
2. Enter or verify your Gemini API key (starts with `AIzaSy...`).
3. Click **⚡ Test Connection**. The background worker will test access to the configured model and display the latency (e.g. `✓ Connected successfully to gemini-3.8-flash. (245.8 ms)`).
4. Click **Save Settings** to persist changes atomically to `.env`.

---

## Development & Testing

### Running Automated Tests
Run the complete automated test suite (all tests use deterministic mocked responses and do not consume API quota):
```powershell
pytest
```

### Code Formatting and Linting
Check and format code with Ruff:
```powershell
ruff check .
ruff format --check .
```
Automatically fix linting issues:
```powershell
ruff check --fix .
ruff format .
```

---

## Troubleshooting

- **API Key Missing:** If the sidebar displays `API Key Missing (.env)`, open Settings (⚙) and enter your Gemini API key.
- **Model 404 / Model Not Found:** If using an experimental model not available in your region or account tier, switch to `gemini-2.5-flash` or `gemini-3.8-flash` in Settings.
- **Rate Limits (429 Quota Exceeded):** If quota is exhausted on the free tier, wait 60 seconds or switch to a paid project tier in Google AI Studio.
- **Proxy / SSL Errors on Windows:** If behind an inspection proxy or VPN, ensure system certificates are trusted or configure `HTTP_PROXY` / `HTTPS_PROXY` environment variables.
