# JARVIS Development Guide

This guide covers developer workflows, code formatting, linting, testing, and debugging.

---

## 1. Development Environment Setup

### 1.1 Requirements
- Windows 11 64-bit
- Python 3.12 (64-bit)
- Git for Windows

### 1.2 Virtual Environment Setup
Ensure PowerShell execution policy permits local scripts, then create and activate the virtual environment:
```powershell
# Set execution policy if not already done:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Create and activate environment:
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install development dependencies:
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 2. Code Quality & Formatting

JARVIS strictly enforces PEP 8, static typing, and formatting using **Ruff**.

### 2.1 Linting
To check the codebase for syntax errors, unused imports, or style violations:
```powershell
ruff check .
```

To automatically fix safe and unsafe lint issues:
```powershell
ruff check --fix .
```

### 2.2 Formatting
Check whether files conform to formatting standards:
```powershell
ruff format --check .
```

Reformat all files in place:
```powershell
ruff format .
```

---

## 3. Testing Guide

Testing is executed with **pytest** and **pytest-qt**. All standard automated tests run with mocked SDK clients and require no internet access or API quota.

### 3.1 Running the Full Test Suite
```powershell
pytest
```

### 3.2 Running Specific Test Categories
Run unit tests only:
```powershell
pytest tests/unit/
```

Run UI and integration tests only:
```powershell
pytest tests/integration/
```

Run Phase 2 provider and conversation tests specifically:
```powershell
pytest tests/unit/test_gemini_provider.py tests/unit/test_conversation.py tests/unit/test_workers.py -v
```

---

## 4. Live Gemini API Verification

To verify connectivity against live Google Gemini endpoints:
1. Ensure your Gemini API key is configured in `.env`:
   ```env
   GEMINI_API_KEY=AIzaSy...
   GEMINI_MODEL=gemini-3.8-flash
   ```
2. Run the application:
   ```powershell
   python app.py
   ```
3. Open **⚙ System Settings** and click **⚡ Test Connection**.
4. Send a test message in the chat panel (e.g. `Hello JARVIS, explain your architecture in one sentence.`).
5. Observe real-time token streaming and response completion.

---

## 5. Debugging & Troubleshooting

### 5.1 Debug Mode
To run the application with verbose debug logging:
1. Set `DEBUG=true` and `LOG_LEVEL=DEBUG` in your `.env` file.
2. Launch the application:
   ```powershell
   python app.py
   ```
3. Inspect live log streams in `logs/jarvis.log`.

### 5.2 Common Gemini Errors
- **`400 / 401 / 403 API_KEY_INVALID`:** Verify that the key in `.env` is exact without surrounding quotes or spaces.
- **`404 Model Not Found`:** Verify that the model name (e.g. `gemini-3.8-flash` or `gemini-2.5-flash`) is supported in your region and account tier.
- **`429 Resource Exhausted`:** Google AI Studio free tier limits requests to 15 RPM. Wait a minute before retrying.
