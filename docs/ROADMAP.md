# JARVIS Engineering Roadmap (12 Phases)

This roadmap details the 12 engineering phases to build JARVIS into a full personal AI desktop agent on Windows 11.

---

## Phase Status Summary

| Phase | Title | Status | Description |
| :--- | :--- | :---: | :--- |
| **Phase 1** | **Foundation, Architecture & Desktop UI** | **COMPLETE** | Project structure, PySide6 UI, configuration, security contracts, and logging. |
| **Phase 2** | **Gemini Integration & Streaming** | **COMPLETE** | Official `google-genai` SDK, token streaming, multi-turn history, background workers, and Settings UI. |
| **Phase 3** | **Agent Core & Planning** | *Planned* | ReAct reasoning loops, multi-step planner, task graphs, error recovery. |
| **Phase 4** | **Security & Permission System** | *Planned* | Interactive confirmation dialogs, sandboxed execution, audit logs. |
| **Phase 5** | **Memory System** | *Planned* | Vector memory, full-text SQLite search, semantic indexing, user profiling. |
| **Phase 6** | **Windows Desktop Control** | *Planned* | Windows UI automation, window management, keyboard/mouse emulation. |
| **Phase 7** | **Browser Agent** | *Planned* | Playwright automation, DOM extraction, web tasks, session isolation. |
| **Phase 8** | **File System & Terminal Agent** | *Planned* | Safe file operations, structured PowerShell execution, diff previews. |
| **Phase 9** | **Voice Engine & Gemini Live** | *Planned* | Real-time audio streaming, Gemini Live API, low-latency duplex voice. |
| **Phase 10**| **Wake Word & Voice Experience** | *Planned* | Offline wake-word detection, continuous background listening, chime cues. |
| **Phase 11**| **Vision & Screen Understanding** | *Planned* | Screen capture, region inspection, multimodal visual analysis with Gemini. |
| **Phase 12**| **Integration, Hardening & Release** | *Planned* | End-to-end integration, performance profiling, packaging into Windows installer. |

---

## Detailed Phase Breakdown

### Phase 1 — Foundation, Architecture & Desktop UI
- **Status:** **COMPLETE**
- **Deliverables:**
  - [x] Python 3.12 x64 modular monolithic directory structure.
  - [x] PySide6 desktop UI with dark futuristic theme, Persian (RTL) & English (LTR) text support.
  - [x] Pydantic Settings configuration with `.env` support and `SecretStr` masking.
  - [x] Centralized logging with `SecretRedactorFilter` scrubbing credentials.
  - [x] Core contracts: `BaseAIProvider`, `BaseTool`, `BasePlanner`, `BaseMemoryStore`.
  - [x] Strict default-deny permission manager (`StrictDefaultDenyPermissionManager`).
  - [x] Synchronous `EventBus` and `TaskManager`.
  - [x] Local SQLite persistence with WAL mode.
  - [x] Automated test suite and Ruff compliance.

---

### Phase 2 — Gemini Integration & Streaming
- **Status:** **COMPLETE**
- **Deliverables:**
  - [x] Official `google-genai` SDK integration (`genai.Client`).
  - [x] Configurable models (default: `gemini-3.8-flash`) with temperature, token limits, and timeouts.
  - [x] Incremental token streaming via dedicated `GeminiStreamWorker` (QThread).
  - [x] Thread-safe UI updates without GUI blocking or freezing.
  - [x] Multi-turn conversation context formatting and bounded history limits.
  - [x] User-initiated cancellation ("Cancel" button) safely terminating streaming workers.
  - [x] Secure Settings UI: password-masked API key edit, show/hide toggle, and atomic `.env` save.
  - [x] Non-blocking "Test Connection" tool distinguishing auth, quota, model, network, and timeout errors.
  - [x] SQLite message persistence with delivery status (`completed`, `streaming`, `cancelled`, `failed`) and model tags.
  - [x] New Chat (+ New Chat) and Clear Chat toolbar actions.
  - [x] 53 automated unit and integration tests passing.

---

### Phase 3 — Agent Core & Planning
- **Status:** *Not Implemented (Next Phase)*
- **Focus:** Autonomous reasoning, tool decomposition, and multi-step plan execution.
- **Key Tasks:**
  - Implement dynamic ReAct (Reason + Act) agent loop.
  - Goal decomposition into directed acyclic plan graphs (`Plan`, `PlanStep`).
  - Asynchronous background worker threads for agent execution.
  - Dynamic replanning on tool failures.

---

### Phase 4 — Security & Permission System
- **Status:** *Foundation Completed in Phase 1; Full Enforcement Pending*
- **Focus:** User approval dialogs, operation sandboxing, and non-bypassable security checks.
- **Key Tasks:**
  - Build PySide6 interactive permission confirmation modals.
  - Enforce action categorizations (`READ_ONLY`, `REVERSIBLE`, `FILE_MODIFICATION`, `DESTRUCTIVE`, `SYSTEM_OPERATION`).
  - Implement permission rule caching and session-based grants.
  - Tamper-resistant audit logging of all executed actions.

---

### Phase 5 — Memory System
- **Status:** *Foundation (SQLite) Completed in Phase 1 & 2; Advanced Semantic Memory Pending*
- **Focus:** Persistent long-term memory, conversation recall, and user preference indexing.
- **Key Tasks:**
  - Full-text search (FTS5) in SQLite for conversation archives.
  - Lightweight local semantic embeddings for episodic memory retrieval.
  - Context window compression and conversation summarization.
  - User persona and preference management.

---

### Phase 6 — Windows Desktop Control
- **Status:** *Not Implemented*
- **Focus:** Native Windows 11 interaction and accessibility automation.
- **Key Tasks:**
  - Windows UI Automation (`pywinauto` / `UIAutomationCore`).
  - Window focus, minimize, maximize, and virtual desktop management.
  - Controlled mouse and keyboard inputs with safety fail-safes (e.g. corner abort).

---

### Phase 7 — Browser Agent
- **Status:** *Not Implemented*
- **Focus:** Headless and headed browser automation for personal workflows.
- **Key Tasks:**
  - Playwright browser integration.
  - Web scraping, form submission, and authenticated session isolation.
  - Accessibility tree extraction for fast semantic DOM parsing.

---

### Phase 8 — File System & Terminal Agent
- **Status:** *Not Implemented*
- **Focus:** Controlled file manipulation and PowerShell terminal execution.
- **Key Tasks:**
  - Safe file inspection, search, creation, and modification with unified diff previews.
  - Controlled PowerShell execution with strict command blacklisting and timeout enforcement.
  - Permission-gated execution for write or deletion operations.

---

### Phase 9 — Voice Engine & Gemini Live
- **Status:** *Not Implemented*
- **Focus:** Duplex streaming voice interaction via Gemini Live API.
- **Key Tasks:**
  - Audio capture and playback pipeline (`PyAudio` / `sounddevice`).
  - Low-latency bidirectional WebSocket connection to Gemini Live API.
  - Interruption detection and audio streaming synchronization.

---

### Phase 10 — Wake Word & Voice Experience
- **Status:** *Not Implemented*
- **Focus:** Hands-free activation and conversational voice indicators.
- **Key Tasks:**
  - Offline local wake-word engine (e.g. `openWakeWord` or `Porcupine`) optimized for Intel i5 CPU.
  - Low-power continuous listening daemon.
  - Auditory state indicators (activation chime, thinking sound, completion cue).

---

### Phase 11 — Vision & Screen Understanding
- **Status:** *Not Implemented*
- **Focus:** Multimodal comprehension of user desktop and active applications.
- **Key Tasks:**
  - High-performance screen and window capture (`mss` / Windows Desktop Duplication API).
  - Region-of-interest cropping to minimize cloud upload bandwidth.
  - Multimodal Gemini prompt integration with image context.

---

### Phase 12 — Integration, Hardening & Release
- **Status:** *Not Implemented*
- **Focus:** Production hardening, system benchmarks, and Windows distribution.
- **Key Tasks:**
  - End-to-end stress testing across all integrated capabilities.
  - CPU and RAM profiling on target hardware (Intel i5-6300U / 16 GB RAM).
  - Packaging with PyInstaller / Inno Setup for one-click native Windows installation.
