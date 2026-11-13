"""Windows Control Service: Native Win32 application, window, audio, display, and power operations.

Implements desktop management using pure ctypes and standard library APIs with zero
external dependencies, strict target validation, and deterministic structured outputs.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import threading
import winreg
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path
from typing import Any

from config import Settings, get_settings
from infrastructure.logging import get_logger
from tools.windows.exceptions import (
    ApplicationNotFoundError,
    AudioEndpointError,
    ComApartmentMismatchError,
    DisplayControlError,
    PowerControlError,
    TargetValidationError,
)
from tools.windows.models import (
    AppInfo,
    AudioOperationResult,
    BrightnessState,
    PowerState,
    ProcessMetadata,
    WindowInfo,
    WindowState,
)
from tools.windows.target_validation import TargetValidator

logger = get_logger("windows.service")

# --- Win32 Constants & Type Definitions ---
HRESULT = ctypes.c_long
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

TH32CS_SNAPPROCESS = 0x00000002
SW_HIDE = 0
SW_MAXIMIZE = 3
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_CLOSE = 0x0010

EWX_LOGOFF = 0x00000000
EWX_SHUTDOWN = 0x00000001
EWX_REBOOT = 0x00000002
EWX_FORCEIFHUNG = 0x00000010


# --- Process Snapshot Structure ---
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


# --- Power Status Structure ---
class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),
        ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


# --- Physical Monitor Structure for DXVA2 ---
class PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [
        ("hPhysicalMonitor", wintypes.HANDLE),
        ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
    ]


# --- Core Audio COM Definitions ---
CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_IAudioEndpointVolume = "{5CDF2C82-841E-4546-9722-0CF74078229A}"


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]

    @classmethod
    def from_str(cls, s: str) -> GUID:
        guid = cls()
        ctypes.windll.ole32.CLSIDFromString(s, ctypes.byref(guid))
        return guid


class IMMDeviceEnumeratorVtbl(ctypes.Structure):
    pass


class IMMDeviceEnumerator(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(IMMDeviceEnumeratorVtbl))]


IMMDeviceEnumeratorVtbl._fields_ = [
    ("QueryInterface", ctypes.c_void_p),
    ("AddRef", ctypes.c_void_p),
    ("Release", ctypes.c_void_p),
    ("EnumAudioEndpoints", ctypes.c_void_p),
    (
        "GetDefaultAudioEndpoint",
        ctypes.WINFUNCTYPE(
            HRESULT,
            ctypes.POINTER(IMMDeviceEnumerator),
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ),
    ),
    ("GetDevice", ctypes.c_void_p),
    ("RegisterEndpointNotificationCallback", ctypes.c_void_p),
    ("UnregisterEndpointNotificationCallback", ctypes.c_void_p),
]


class IMMDeviceVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", ctypes.c_void_p),
        ("AddRef", ctypes.c_void_p),
        ("Release", ctypes.c_void_p),
        (
            "Activate",
            ctypes.WINFUNCTYPE(
                HRESULT,
                ctypes.c_void_p,
                ctypes.POINTER(GUID),
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ),
        ),
        ("OpenPropertyStore", ctypes.c_void_p),
        ("GetId", ctypes.c_void_p),
        ("GetState", ctypes.c_void_p),
    ]


class IMMDevice(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(IMMDeviceVtbl))]


class IAudioEndpointVolumeVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", ctypes.c_void_p),
        ("AddRef", ctypes.c_void_p),
        ("Release", ctypes.c_void_p),
        ("RegisterControlChangeNotify", ctypes.c_void_p),
        ("UnregisterControlChangeNotify", ctypes.c_void_p),
        ("GetChannelCount", ctypes.c_void_p),
        ("SetMasterVolumeLevel", ctypes.c_void_p),
        (
            "SetMasterVolumeLevelScalar",
            ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_float, ctypes.c_void_p),
        ),
        ("GetMasterVolumeLevel", ctypes.c_void_p),
        (
            "GetMasterVolumeLevelScalar",
            ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float)),
        ),
        ("SetChannelVolumeLevel", ctypes.c_void_p),
        ("SetChannelVolumeLevelScalar", ctypes.c_void_p),
        ("GetChannelVolumeLevel", ctypes.c_void_p),
        ("GetChannelVolumeLevelScalar", ctypes.c_void_p),
        (
            "SetMute",
            ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wintypes.BOOL, ctypes.c_void_p),
        ),
        (
            "GetMute",
            ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL)),
        ),
    ]


class IAudioEndpointVolume(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(IAudioEndpointVolumeVtbl))]


class WindowsControlService:
    """Core native service managing desktop applications, windows, audio, display, and power."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._ole32 = ctypes.windll.ole32

        # Initialize COM library for the thread if not initialized
        with contextlib.suppress(Exception):
            self._ole32.CoInitialize(None)

        # Built-in standard catalog of known Windows applications
        self._standard_catalog: dict[str, tuple[str, list[str]]] = {
            "notepad": ("Notepad", ["notepad.exe"]),
            "calc": ("Calculator", ["calc.exe", "calculatorapp.exe"]),
            "calculator": ("Calculator", ["calc.exe", "calculatorapp.exe"]),
            "explorer": ("File Explorer", ["explorer.exe"]),
            "cmd": ("Command Prompt", ["cmd.exe"]),
            "wt": ("Windows Terminal", ["wt.exe"]),
            "terminal": ("Windows Terminal", ["wt.exe"]),
            "mspaint": ("Paint", ["mspaint.exe"]),
            "paint": ("Paint", ["mspaint.exe"]),
            "taskmgr": ("Task Manager", ["taskmgr.exe"]),
            "chrome": ("Google Chrome", ["chrome.exe"]),
            "msedge": ("Microsoft Edge", ["msedge.exe"]),
            "edge": ("Microsoft Edge", ["msedge.exe"]),
            "firefox": ("Mozilla Firefox", ["firefox.exe"]),
            "brave": ("Brave Browser", ["brave.exe"]),
            "code": ("Visual Studio Code", ["code.exe"]),
            "vscode": ("Visual Studio Code", ["code.exe"]),
        }

    # =========================================================================
    # 1. Native Application Management
    # =========================================================================

    def _resolve_from_registry_app_paths(self, exe_name: str) -> Path | None:
        """Resolve executable path from Windows Registry App Paths."""
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            sub_key = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
            try:
                with winreg.OpenKey(root, sub_key) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val:
                        p = Path(os.path.expandvars(str(val).strip("\"';"))).resolve()
                        if p.is_file():
                            return p
            except OSError:
                continue
        return None

    def _find_executable_on_system(self, candidates: list[str]) -> Path | None:
        """Locate executable binary across Windows System32, Program Files, and App Paths."""
        sys_root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        search_dirs = [
            sys_root / "System32",
            sys_root,
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
            if os.environ.get("LOCALAPPDATA")
            else None,
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
            if os.environ.get("LOCALAPPDATA")
            else None,
        ]

        for cand in candidates:
            # 1. Check App Paths in registry
            reg_path = self._resolve_from_registry_app_paths(cand)
            if reg_path and reg_path.is_file():
                return reg_path

            # 2. Check standard search directories
            for s_dir in search_dirs:
                if not s_dir or not s_dir.is_dir():
                    continue
                # Direct check
                direct = s_dir / cand
                if direct.is_file():
                    return direct.resolve()
                # Recursive shallow search in Program Files
                if "Program Files" in str(s_dir) or "Programs" in str(s_dir):
                    try:
                        for entry in s_dir.glob(f"*/{cand}"):
                            if entry.is_file():
                                return entry.resolve()
                    except (OSError, PermissionError):
                        continue
        return None

    def get_application_catalog(self) -> list[AppInfo]:
        """Enumerate supported applications from allowlist and catalog."""
        allowlist = [a.lower().strip() for a in self.settings.windows_app_allowlist]
        running_procs = self.list_running_processes()

        catalog: list[AppInfo] = []
        for app_id, (display_name, exes) in self._standard_catalog.items():
            if app_id not in allowlist:
                continue

            exe_path = self._find_executable_on_system(exes)
            is_installed = exe_path is not None and exe_path.is_file()
            running_pids = [
                p.pid for p in running_procs if any(p.name.lower() == e.lower() for e in exes)
            ]

            catalog.append(
                AppInfo(
                    app_id=app_id,
                    display_name=display_name,
                    executable_path=str(exe_path) if exe_path else "",
                    is_installed=is_installed,
                    is_running=len(running_pids) > 0,
                    running_pids=running_pids,
                )
            )
        return catalog

    def resolve_application(self, app_identifier: str) -> AppInfo:
        """Resolve an application identifier to an approved executable path."""
        norm_id = app_identifier.lower().strip().replace(".exe", "")
        allowlist = [a.lower().strip() for a in self.settings.windows_app_allowlist]

        if norm_id not in allowlist:
            raise ApplicationNotFoundError(
                f"Application '{app_identifier}' is not present in the configured allowlist "
                f"({', '.join(sorted(allowlist))}). Arbitrary applications cannot be launched."
            )

        if norm_id not in self._standard_catalog:
            # Check if identifier exists as a registered application
            reg_path = self._resolve_from_registry_app_paths(f"{norm_id}.exe")
            if not reg_path:
                raise ApplicationNotFoundError(
                    f"Application '{app_identifier}' could not be resolved."
                )
            display_name = norm_id.capitalize()
            exes = [f"{norm_id}.exe"]
            resolved_path = reg_path
        else:
            display_name, exes = self._standard_catalog[norm_id]
            resolved_path = self._find_executable_on_system(exes)

        if not resolved_path or not resolved_path.is_file():
            raise ApplicationNotFoundError(
                f"Application '{app_identifier}' ({display_name}) is supported in configuration but not installed on this system."
            )

        # Validate executable identity & attributes
        TargetValidator.validate_executable_path(str(resolved_path))

        running_procs = self.list_running_processes()
        running_pids = [
            p.pid for p in running_procs if any(p.name.lower() == e.lower() for e in exes)
        ]

        return AppInfo(
            app_id=norm_id,
            display_name=display_name,
            executable_path=str(resolved_path),
            is_installed=True,
            is_running=len(running_pids) > 0,
            running_pids=running_pids,
        )

    def launch_application(self, app_identifier: str) -> dict[str, Any]:
        """Launch an approved application without shell execution or privilege elevation."""
        if not self.settings.windows_app_launch_enabled:
            raise ApplicationNotFoundError(
                "Application launching is disabled by user policy (windows_app_launch_enabled=False)."
            )

        app_info = self.resolve_application(app_identifier)
        exe_path = TargetValidator.validate_executable_path(app_info.executable_path)

        logger.info(f"Launching verified desktop application: {app_info.display_name} ({exe_path})")
        # Launch directly without shell
        proc = subprocess.Popen(
            [str(exe_path)],
            shell=False,
            close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
        )

        return {
            "app_id": app_info.app_id,
            "display_name": app_info.display_name,
            "executable_path": str(exe_path),
            "pid": proc.pid,
            "status": "launched",
        }

    def list_running_processes(self) -> list[ProcessMetadata]:
        """Enumerate running processes using Toolhelp32 snapshot."""
        h_snapshot = self._kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h_snapshot == wintypes.HANDLE(-1).value:
            return []

        processes: list[ProcessMetadata] = []
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

        try:
            success = self._kernel32.Process32FirstW(h_snapshot, ctypes.byref(entry))
            while success:
                pid = entry.th32ProcessID
                name = entry.szExeFile
                if pid > 0 and name:
                    processes.append(ProcessMetadata(pid=pid, name=name))
                success = self._kernel32.Process32NextW(h_snapshot, ctypes.byref(entry))
        finally:
            self._kernel32.CloseHandle(h_snapshot)

        return processes

    def close_application(
        self,
        app_identifier: str,
        pid: int | None = None,
        graceful: bool = True,
        expected_creation_time: int | None = None,
    ) -> dict[str, Any]:
        """Close a running desktop application gracefully via WM_CLOSE."""
        if not self.settings.windows_app_close_enabled:
            raise ApplicationNotFoundError(
                "Application closing is disabled by user policy (windows_app_close_enabled=False)."
            )

        app_info = self.resolve_application(app_identifier)
        target_pids = [pid] if pid is not None else app_info.running_pids

        if not target_pids:
            return {
                "app_id": app_info.app_id,
                "display_name": app_info.display_name,
                "closed_count": 0,
                "status": "not_running",
            }

        closed_count = 0
        windows = self.list_windows()

        for t_pid in target_pids:
            # Validate target PID is not a protected OS process and matches creation time
            TargetValidator.validate_process_target(
                t_pid, app_info.display_name, expected_creation_time=expected_creation_time
            )

            # Find top-level windows for this process
            proc_windows = [w for w in windows if w.pid == t_pid]
            for w in proc_windows:
                try:
                    self.close_window(
                        w.hwnd,
                        graceful=graceful,
                        expected_pid=t_pid,
                        expected_creation_time=expected_creation_time,
                    )
                    closed_count += 1
                except Exception as exc:
                    logger.warning(f"Failed to close window {w.hwnd} (PID {t_pid}): {exc}")

        return {
            "app_id": app_info.app_id,
            "display_name": app_info.display_name,
            "closed_count": closed_count,
            "target_pids": target_pids,
            "status": "closed" if closed_count > 0 else "close_requested",
        }

    # =========================================================================
    # 2. Window Management
    # =========================================================================

    def list_windows(self, include_invisible: bool = False) -> list[WindowInfo]:
        """Enumerate top-level desktop windows with handles, titles, PIDs, and states."""
        windows: list[WindowInfo] = []
        seen_hwnds: set[int] = set()

        def enum_callback(hwnd: wintypes.HWND, lparam: wintypes.LPARAM) -> bool:
            hwnd_val = int(hwnd)
            if hwnd_val in seen_hwnds:
                return True
            seen_hwnds.add(hwnd_val)

            is_visible = bool(self._user32.IsWindowVisible(hwnd))
            if not include_invisible and not is_visible:
                return True

            length = self._user32.GetWindowTextLengthW(hwnd)
            if length == 0 and not include_invisible:
                return True

            title_buf = ctypes.create_unicode_buffer(length + 1)
            self._user32.GetWindowTextW(hwnd, title_buf, length + 1)
            title = title_buf.value

            class_buf = ctypes.create_unicode_buffer(256)
            self._user32.GetClassNameW(hwnd, class_buf, 256)
            class_name = class_buf.value

            # Filter out protected system shell surfaces unless explicitly requested
            if TargetValidator.is_protected_window_class(class_name):
                return True

            pid = wintypes.DWORD()
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            # Query placement / state
            if self._user32.IsIconic(hwnd):
                state = WindowState.MINIMIZED
            elif self._user32.IsZoomed(hwnd):
                state = WindowState.MAXIMIZED
            elif not is_visible:
                state = WindowState.HIDDEN
            else:
                state = WindowState.NORMAL

            # Query process executable name
            proc_name = ""
            h_proc = self._kernel32.OpenProcess(
                0x1000, False, pid.value
            )  # PROCESS_QUERY_LIMITED_INFORMATION
            if h_proc:
                try:
                    img_buf = ctypes.create_unicode_buffer(260)
                    size = wintypes.DWORD(260)
                    if hasattr(
                        self._kernel32, "QueryFullProcessImageNameW"
                    ) and self._kernel32.QueryFullProcessImageNameW(
                        h_proc, 0, img_buf, ctypes.byref(size)
                    ):
                        proc_name = Path(img_buf.value).name
                finally:
                    self._kernel32.CloseHandle(h_proc)

            creation_time = TargetValidator.get_process_creation_time(pid.value)
            windows.append(
                WindowInfo(
                    hwnd=hwnd_val,
                    title=title,
                    class_name=class_name,
                    pid=pid.value,
                    process_name=proc_name,
                    state=state,
                    is_visible=is_visible,
                    creation_time=creation_time,
                )
            )
            return True

        proc_cb = WNDENUMPROC(enum_callback)

        # Enumerate interactive desktop windows ("Default") if accessible
        DESKTOP_READOBJECTS = 0x0001
        DESKTOP_ENUMERATE = 0x0040
        h_desk = self._user32.OpenDesktopW(
            "Default", 0, False, DESKTOP_READOBJECTS | DESKTOP_ENUMERATE
        )
        if h_desk:
            try:
                self._user32.EnumDesktopWindows(h_desk, proc_cb, 0)
            finally:
                self._user32.CloseDesktop(h_desk)

        # Also enumerate via EnumWindows to capture top-level container/virtual windows
        self._user32.EnumWindows(proc_cb, 0)

        return windows

    def find_windows(
        self,
        query: str | None = None,
        pid: int | None = None,
        app_name: str | None = None,
    ) -> list[WindowInfo]:
        """Find windows matching title substring, PID, or application name."""
        all_windows = self.list_windows()
        matches = []
        q_lower = query.lower().strip() if query else None
        app_lower = app_name.lower().strip() if app_name else None

        for w in all_windows:
            if pid is not None and w.pid != pid:
                continue
            if app_lower and app_lower not in w.process_name.lower():
                continue
            if q_lower and q_lower not in w.title.lower():
                continue
            matches.append(w)
        return matches

    def focus_window(
        self,
        hwnd: int,
        expected_pid: int | None = None,
        expected_creation_time: int | None = None,
    ) -> bool:
        """Bring window to foreground and activate it."""
        TargetValidator.validate_window_handle(
            hwnd,
            expected_pid=expected_pid,
            expected_creation_time=expected_creation_time,
        )
        h = wintypes.HWND(hwnd)

        # If minimized, restore it first
        if self._user32.IsIconic(h):
            self._user32.ShowWindow(h, SW_RESTORE)

        self._user32.SetForegroundWindow(h)
        self._user32.BringWindowToTop(h)
        return True

    def minimize_window(
        self,
        hwnd: int,
        expected_pid: int | None = None,
        expected_creation_time: int | None = None,
    ) -> bool:
        """Minimize a desktop window."""
        TargetValidator.validate_window_handle(
            hwnd,
            expected_pid=expected_pid,
            expected_creation_time=expected_creation_time,
        )
        self._user32.ShowWindow(wintypes.HWND(hwnd), SW_MINIMIZE)
        return True

    def maximize_window(
        self,
        hwnd: int,
        expected_pid: int | None = None,
        expected_creation_time: int | None = None,
    ) -> bool:
        """Maximize a desktop window."""
        TargetValidator.validate_window_handle(
            hwnd,
            expected_pid=expected_pid,
            expected_creation_time=expected_creation_time,
        )
        self._user32.ShowWindow(wintypes.HWND(hwnd), SW_MAXIMIZE)
        return True

    def restore_window(
        self,
        hwnd: int,
        expected_pid: int | None = None,
        expected_creation_time: int | None = None,
    ) -> bool:
        """Restore a minimized or maximized window to normal bounds."""
        TargetValidator.validate_window_handle(
            hwnd,
            expected_pid=expected_pid,
            expected_creation_time=expected_creation_time,
        )
        self._user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
        return True

    def close_window(
        self,
        hwnd: int,
        graceful: bool = True,
        expected_pid: int | None = None,
        expected_creation_time: int | None = None,
    ) -> bool:
        """Close a desktop window gracefully via WM_CLOSE message."""
        TargetValidator.validate_window_handle(
            hwnd,
            expected_pid=expected_pid,
            expected_creation_time=expected_creation_time,
        )
        h = wintypes.HWND(hwnd)
        # Send WM_CLOSE
        res = self._user32.PostMessageW(h, WM_CLOSE, 0, 0)
        return bool(res)

    # =========================================================================
    # 3. Audio Controls (Core Audio COM)
    # =========================================================================

    @contextlib.contextmanager
    def _com_session(self) -> Iterator[None]:
        """Scoped COM initialization for Windows Core Audio.

        Strictly enforces:
        - S_OK (0): New initialization on calling thread -> requires CoUninitialize.
        - S_FALSE (1): Nested initialization in same apartment -> requires CoUninitialize.
        - RPC_E_CHANGED_MODE (0x80010106 / -2147417850): Incompatible existing apartment.
          CoUninitialize must NOT be called. Raises ComApartmentMismatchError for clean-thread recovery.
        """
        if os.name != "nt":
            yield
            return

        needs_uninit = False
        hr = self._ole32.CoInitialize(None)
        hr_unsigned = hr if hr >= 0 else hr + (1 << 32)
        if hr in (0, 1):
            needs_uninit = True
        elif hr in (-2147417850, 0x80010106) or hr_unsigned == 0x80010106:
            needs_uninit = False
            logger.warning(
                "COM apartment-mode mismatch detected (RPC_E_CHANGED_MODE: 0x80010106). "
                "Current thread initialized in incompatible apartment mode; routing to dedicated worker."
            )
            raise ComApartmentMismatchError(
                "Thread is initialized in an incompatible COM apartment (RPC_E_CHANGED_MODE: 0x80010106)."
            )
        else:
            needs_uninit = False
            logger.warning(f"CoInitialize returned unexpected HRESULT: {hex(hr)}")

        try:
            yield
        finally:
            if needs_uninit:
                try:
                    self._ole32.CoUninitialize()
                except Exception as exc:
                    logger.debug(f"CoUninitialize exception: {exc}")

    def _run_with_com(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a COM function within a scoped COM session, recovering via clean thread if apartment mismatched."""
        try:
            with self._com_session():
                return func(*args, **kwargs)
        except ComApartmentMismatchError:
            result: list[Any] = [None]
            err: list[BaseException | None] = [None]

            def clean_thread_worker() -> None:
                try:
                    with self._com_session():
                        result[0] = func(*args, **kwargs)
                except Exception as e:
                    err[0] = e

            worker_thread = threading.Thread(target=clean_thread_worker, name="JarvisCOMWorker")
            worker_thread.start()
            worker_thread.join()

            if err[0] is not None:
                raise err[0] from None
            return result[0]

    def _ensure_com_initialized(self) -> None:
        """Deprecated compatibility shim: callers should use _com_session() or _run_with_com()."""
        try:
            self._ole32.CoInitialize(None)
        except Exception as exc:
            logger.debug(f"CoInitialize check exception: {exc}")

    def _get_audio_endpoint_volume(self) -> Any:
        """Obtain IAudioEndpointVolume interface from default audio render device."""
        clsid_enum = GUID.from_str(CLSID_MMDeviceEnumerator)
        iid_enum = GUID.from_str(IID_IMMDeviceEnumerator)
        iid_vol = GUID.from_str(IID_IAudioEndpointVolume)

        pEnum = ctypes.POINTER(IMMDeviceEnumerator)()
        hr = self._ole32.CoCreateInstance(
            ctypes.byref(clsid_enum),
            None,
            1 | 2 | 4,  # CLSCTX_ALL
            ctypes.byref(iid_enum),
            ctypes.byref(pEnum),
        )
        if hr != 0 or not pEnum:
            raise AudioEndpointError(f"Failed to create IMMDeviceEnumerator (HRESULT: {hex(hr)})")

        pDevice = ctypes.c_void_p()
        # eRender = 0, eMultimedia = 1
        hr = pEnum.contents.lpVtbl.contents.GetDefaultAudioEndpoint(
            pEnum, 0, 1, ctypes.byref(pDevice)
        )
        if hr != 0 or not pDevice:
            with contextlib.suppress(Exception):
                pEnum.contents.lpVtbl.contents.Release(pEnum)
            raise AudioEndpointError(f"No default audio output endpoint found (HRESULT: {hex(hr)})")

        pDevice_typed = ctypes.cast(pDevice, ctypes.POINTER(IMMDevice))
        pEndpointVolume = ctypes.c_void_p()
        try:
            hr = pDevice_typed.contents.lpVtbl.contents.Activate(
                pDevice,
                ctypes.byref(iid_vol),
                1 | 2 | 4,
                None,
                ctypes.byref(pEndpointVolume),
            )
            if hr != 0 or not pEndpointVolume:
                raise AudioEndpointError(
                    f"Failed to activate IAudioEndpointVolume (HRESULT: {hex(hr)})"
                )
        finally:
            with contextlib.suppress(Exception):
                pDevice_typed.contents.lpVtbl.contents.Release(pDevice)
            with contextlib.suppress(Exception):
                pEnum.contents.lpVtbl.contents.Release(pEnum)

        return ctypes.cast(pEndpointVolume, ctypes.POINTER(IAudioEndpointVolume))

    def _get_audio_status_internal(self) -> AudioOperationResult:
        pVol = None
        try:
            pVol = self._get_audio_endpoint_volume()
            vol_float = ctypes.c_float()
            hr1 = pVol.contents.lpVtbl.contents.GetMasterVolumeLevelScalar(
                pVol, ctypes.byref(vol_float)
            )
            mute_bool = wintypes.BOOL()
            hr2 = pVol.contents.lpVtbl.contents.GetMute(pVol, ctypes.byref(mute_bool))

            if hr1 != 0 or hr2 != 0:
                raise AudioEndpointError("Failed to query volume or mute state from endpoint.")

            vol_val = round(vol_float.value * 100.0, 1)
            mute_val = bool(mute_bool.value)
            return AudioOperationResult(
                volume_percent=vol_val,
                is_muted=mute_val,
                device_name="Default Multimedia Output",
                supported=True,
                success=True,
                operation="get_status",
                requested_value=None,
                actual_value={"volume_percent": vol_val, "is_muted": mute_val},
                verified=True,
            )
        except Exception as exc:
            logger.warning(f"Audio inspection failed: {exc}")
            raise AudioEndpointError(f"Windows Core Audio query failed: {exc}") from exc
        finally:
            if pVol:
                with contextlib.suppress(Exception):
                    pVol.contents.lpVtbl.contents.Release(pVol)

    def get_audio_status(self) -> AudioOperationResult:
        """Read current master output volume percentage and mute state."""
        return self._run_with_com(self._get_audio_status_internal)

    def _set_volume_internal(self, percent: float) -> AudioOperationResult:
        pVol = None
        try:
            pVol = self._get_audio_endpoint_volume()
            scalar = ctypes.c_float(percent / 100.0)
            hr = pVol.contents.lpVtbl.contents.SetMasterVolumeLevelScalar(pVol, scalar, None)
            if hr < 0:
                raise AudioEndpointError(f"SetMasterVolumeLevelScalar failed (HRESULT: {hex(hr)})")

            # Independent read-back from endpoint
            vol_read = ctypes.c_float()
            hr_vol = pVol.contents.lpVtbl.contents.GetMasterVolumeLevelScalar(
                pVol, ctypes.byref(vol_read)
            )
            mute_read = wintypes.BOOL()
            pVol.contents.lpVtbl.contents.GetMute(pVol, ctypes.byref(mute_read))

            if hr_vol != 0:
                raise AudioEndpointError("Failed to read back volume state after modification.")

            actual_vol = round(vol_read.value * 100.0, 1)
            actual_muted = bool(mute_read.value)

            # Verification: within 1.5% margin due to scalar floating point quantization
            verified = abs(actual_vol - percent) <= 1.5
            if not verified:
                raise AudioEndpointError(
                    f"Volume verification mismatch: requested {percent}%, read back {actual_vol}%"
                )

            return AudioOperationResult(
                volume_percent=actual_vol,
                is_muted=actual_muted,
                device_name="Default Multimedia Output",
                supported=True,
                success=True,
                operation="set_volume",
                requested_value=percent,
                actual_value=actual_vol,
                verified=True,
            )
        except Exception as exc:
            logger.error(f"Set volume failed: {exc}")
            raise AudioEndpointError(f"Failed to set volume to {percent}%: {exc}") from exc
        finally:
            if pVol:
                with contextlib.suppress(Exception):
                    pVol.contents.lpVtbl.contents.Release(pVol)

    def set_volume(self, percent: float) -> AudioOperationResult:
        """Set master output volume percentage (0.0 to 100.0) with read-back verification."""
        if not self.settings.windows_audio_control_enabled:
            raise AudioEndpointError("Audio control is disabled by user policy.")

        if percent < 0.0 or percent > 100.0:
            raise TargetValidationError(
                f"Volume percent must be between 0.0 and 100.0 (received {percent})."
            )

        return self._run_with_com(self._set_volume_internal, percent)

    def _set_mute_internal(self, mute: bool) -> AudioOperationResult:
        pVol = None
        try:
            pVol = self._get_audio_endpoint_volume()
            b_mute = wintypes.BOOL(mute)
            hr = pVol.contents.lpVtbl.contents.SetMute(pVol, b_mute, None)
            if hr < 0:
                raise AudioEndpointError(f"SetMute failed (HRESULT: {hex(hr)})")

            # Independent read-back from endpoint
            mute_read = wintypes.BOOL()
            hr_mute = pVol.contents.lpVtbl.contents.GetMute(pVol, ctypes.byref(mute_read))
            vol_read = ctypes.c_float()
            pVol.contents.lpVtbl.contents.GetMasterVolumeLevelScalar(pVol, ctypes.byref(vol_read))

            if hr_mute != 0:
                raise AudioEndpointError("Failed to read back mute state after modification.")

            actual_muted = bool(mute_read.value)
            actual_vol = round(vol_read.value * 100.0, 1)

            # Verification: observed state must strictly match requested state
            verified = actual_muted == mute
            if not verified:
                raise AudioEndpointError(
                    f"Audio mute state verification mismatch: requested {mute}, read back {actual_muted}"
                )

            return AudioOperationResult(
                volume_percent=actual_vol,
                is_muted=actual_muted,
                device_name="Default Multimedia Output",
                supported=True,
                success=True,
                operation="mute" if mute else "unmute",
                requested_value=mute,
                actual_value=actual_muted,
                verified=True,
            )
        except Exception as exc:
            logger.error(f"Set mute failed: {exc}")
            raise AudioEndpointError(f"Failed to set audio mute to {mute}: {exc}") from exc
        finally:
            if pVol:
                with contextlib.suppress(Exception):
                    pVol.contents.lpVtbl.contents.Release(pVol)

    def set_mute(self, mute: bool) -> AudioOperationResult:
        """Mute or unmute master output audio with independent read-back verification."""
        if not self.settings.windows_audio_control_enabled:
            raise AudioEndpointError("Audio control is disabled by user policy.")

        return self._run_with_com(self._set_mute_internal, mute)

    # =========================================================================
    # 4. Display and Brightness Controls (DXVA2 Monitor API)
    # =========================================================================

    def get_brightness(self) -> BrightnessState:
        """Read physical monitor brightness percentage where supported."""
        try:
            dxva2 = ctypes.windll.dxva2
            hmon = self._user32.MonitorFromWindow(0, 1)  # MONITOR_DEFAULTTOPRIMARY
            if not hmon:
                return BrightnessState(
                    supported=False,
                    error_reason="No primary display monitor handle found.",
                )

            count = wintypes.DWORD()
            res = dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count))
            if not res or count.value == 0:
                return BrightnessState(
                    supported=False,
                    error_reason="Display driver or monitor bus does not expose physical monitor handles.",
                )

            mons = (PHYSICAL_MONITOR * count.value)()
            if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, count.value, mons):
                return BrightnessState(
                    supported=False,
                    error_reason="Failed to acquire physical monitor descriptors from display driver.",
                )

            try:
                hPhys = mons[0].hPhysicalMonitor
                if not hPhys:
                    return BrightnessState(
                        supported=False,
                        error_reason="Physical monitor handle is null or unsupported over current connection.",
                    )

                min_b = wintypes.DWORD()
                cur_b = wintypes.DWORD()
                max_b = wintypes.DWORD()
                if not dxva2.GetMonitorBrightness(
                    hPhys, ctypes.byref(min_b), ctypes.byref(cur_b), ctypes.byref(max_b)
                ):
                    return BrightnessState(
                        supported=False,
                        error_reason="Monitor does not support DDC/CI brightness commands or driver returned error.",
                    )

                return BrightnessState(
                    supported=True,
                    brightness_percent=int(cur_b.value),
                    min_brightness=int(min_b.value),
                    max_brightness=int(max_b.value),
                    monitor_description=mons[0].szPhysicalMonitorDescription,
                )
            finally:
                dxva2.DestroyPhysicalMonitors(count.value, mons)

        except Exception as exc:
            return BrightnessState(
                supported=False,
                error_reason=f"Display brightness inspection unsupported on this platform: {exc}",
            )

    def set_brightness(self, percent: int) -> BrightnessState:
        """Set physical monitor brightness percentage (0 - 100) where supported."""
        if not self.settings.windows_display_control_enabled:
            raise DisplayControlError("Display control is disabled by user policy.")

        if percent < 0 or percent > 100:
            raise TargetValidationError(
                f"Brightness percent must be between 0 and 100 (received {percent})."
            )

        curr = self.get_brightness()
        if not curr.supported:
            raise DisplayControlError(
                f"Brightness adjustment is unsupported on current display: {curr.error_reason}"
            )

        try:
            dxva2 = ctypes.windll.dxva2
            hmon = self._user32.MonitorFromWindow(0, 1)
            count = wintypes.DWORD()
            dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count))
            mons = (PHYSICAL_MONITOR * count.value)()
            dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, count.value, mons)

            try:
                hPhys = mons[0].hPhysicalMonitor
                res = dxva2.SetMonitorBrightness(hPhys, wintypes.DWORD(percent))
                if not res:
                    raise DisplayControlError(
                        "SetMonitorBrightness API call returned failure from driver."
                    )
            finally:
                dxva2.DestroyPhysicalMonitors(count.value, mons)

            return self.get_brightness()
        except Exception as exc:
            raise DisplayControlError(f"Failed to set brightness to {percent}%: {exc}") from exc

    # =========================================================================
    # 5. Power-State Operations
    # =========================================================================

    def get_power_status(self) -> PowerState:
        """Read system AC line status, battery percentage, and charging state."""
        sps = SYSTEM_POWER_STATUS()
        if not self._kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            raise PowerControlError("Failed to query GetSystemPowerStatus.")

        ac_map = {0: "offline", 1: "online", 255: "unknown"}
        ac_str = ac_map.get(sps.ACLineStatus, "unknown")

        bat_pct = int(sps.BatteryLifePercent)
        if bat_pct == 255:
            bat_pct = 100  # Desktop / AC-only

        # Battery flag bitmask: 1=High, 2=Low, 4=Critical, 8=Charging, 128=No system battery
        if sps.BatteryFlag & 128:
            bat_status = "no_battery"
        elif sps.BatteryFlag & 8:
            bat_status = "charging"
        elif sps.BatteryFlag & 4:
            bat_status = "critical"
        elif sps.ACLineStatus == 1:
            bat_status = "charging"
        else:
            bat_status = "discharging"

        life_secs = int(sps.BatteryLifeTime) if sps.BatteryLifeTime != 0xFFFFFFFF else None

        return PowerState(
            ac_line_status=ac_str,
            battery_percent=min(max(bat_pct, 0), 100),
            battery_status=bat_status,
            battery_life_time_seconds=life_secs,
        )

    def lock_workstation(self) -> bool:
        """Lock the current Windows workstation session."""
        if not self.settings.windows_power_control_enabled:
            raise PowerControlError("Power operations are disabled by user policy.")
        res = self._user32.LockWorkStation()
        if not res:
            raise PowerControlError("LockWorkStation Win32 call failed.")
        return True

    def sleep(self, hibernate: bool = False) -> bool:
        """Place system into sleep or hibernate state."""
        if not self.settings.windows_power_control_enabled:
            raise PowerControlError("Power operations are disabled by user policy.")
        try:
            powrprof = ctypes.windll.powrprof
            # SetSuspendState(bHibernate, bForce, bWakeupEventsDisabled)
            res = powrprof.SetSuspendState(
                wintypes.BOOL(hibernate), wintypes.BOOL(False), wintypes.BOOL(False)
            )
            return bool(res)
        except Exception as exc:
            raise PowerControlError(f"SetSuspendState failed: {exc}") from exc

    def restart(self, force: bool = False) -> bool:
        """Restart Windows PC (requires high-impact human approval)."""
        if not self.settings.windows_power_control_enabled:
            raise PowerControlError("Power operations are disabled by user policy.")
        flags = EWX_REBOOT | (EWX_FORCEIFHUNG if force else 0)
        res = self._user32.ExitWindowsEx(flags, 0)
        if not res:
            raise PowerControlError("ExitWindowsEx(EWX_REBOOT) failed.")
        return True

    def shutdown(self, force: bool = False) -> bool:
        """Shut down Windows PC (requires high-impact human approval)."""
        if not self.settings.windows_power_control_enabled:
            raise PowerControlError("Power operations are disabled by user policy.")
        flags = EWX_SHUTDOWN | (EWX_FORCEIFHUNG if force else 0)
        res = self._user32.ExitWindowsEx(flags, 0)
        if not res:
            raise PowerControlError("ExitWindowsEx(EWX_SHUTDOWN) failed.")
        return True
