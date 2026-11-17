"""Universal Windows Application Discovery & Fuzzy Matcher for JARVIS.

Discovers virtually all installed Windows desktop applications from:
1. Windows Registered Applications (Registry App Paths in HKLM and HKCU)
2. Windows Start Menu Shortcuts (User and System Start Menu directories)
3. Windows Packaged / UWP Apps (via Get-StartApps and Shell:AppsFolder AUMIDs)
4. System PATH executables

Provides bilingual Persian-English natural language fuzzy resolution and launch capabilities.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import threading
import time
import winreg
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("windows.discovery")


@dataclass
class DiscoveredApplication:
    """Represents a discovered Windows desktop or packaged application."""

    app_id: str
    name: str
    target: str  # File path to .exe or AUMID string (e.g. Microsoft.WindowsCalculator_8wekyb3d8bbwe!App)
    launch_type: str  # "exe" or "aumid"
    aliases: list[str] = field(default_factory=list)
    is_packaged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "name": self.name,
            "target": self.target,
            "launch_type": self.launch_type,
            "aliases": self.aliases,
            "is_packaged": self.is_packaged,
        }


class WindowsApplicationDiscovery:
    """Universal application discovery and natural language resolver."""

    # Persian colloquial and technical alias dictionary
    PERSIAN_APP_ALIASES: dict[str, list[str]] = {
        "فتوشاپ": ["photoshop", "adobe photoshop"],
        "کروم": ["chrome", "google chrome"],
        "گوگل کروم": ["chrome", "google chrome"],
        "اج": ["edge", "microsoft edge"],
        "ادج": ["edge", "microsoft edge"],
        "مایکروسافت اج": ["edge", "microsoft edge"],
        "فایرفاکس": ["firefox", "mozilla firefox"],
        "بریو": ["brave"],
        "کد": ["visual studio code", "code", "vscode"],
        "وی اس کد": ["visual studio code", "code", "vscode"],
        "ویژوال استودیو": ["visual studio", "devenv"],
        "ویژوال استودیو کد": ["visual studio code", "code", "vscode"],
        "تلگرام": ["telegram"],
        "واتساپ": ["whatsapp"],
        "دیسکورد": ["discord"],
        "اسپاتیفای": ["spotify"],
        "نوت پد": ["notepad"],
        "یادداشت": ["notepad", "sticky notes"],
        "ماشین حساب": ["calculator", "calc"],
        "ترمینال": ["terminal", "windows terminal", "wt"],
        "خط فرمان": ["command prompt", "cmd"],
        "سی ام دی": ["cmd", "command prompt"],
        "پینت": ["paint", "mspaint"],
        "نقاشی": ["paint", "mspaint"],
        "تنظیمات": ["settings", "control panel"],
        "کنترل پنل": ["control panel"],
        "اکسپلورر": ["file explorer", "explorer"],
        "فایل منیجر": ["file explorer", "explorer"],
        "این کامپیوتر": ["this pc", "file explorer"],
        "دوربین": ["camera"],
        "ساعت": ["clock", "alarms"],
        "آلارم": ["clock"],
        "آنتی گرویتی": ["antigravity", "antigravity ide"],
        "استیم": ["steam"],
        "ورد": ["word", "microsoft word"],
        "اکسل": ["excel", "microsoft excel"],
        "پاورپوینت": ["powerpoint", "microsoft powerpoint"],
        "پی دی اف خوان": ["acrobat", "adobe acrobat", "foxit"],
        "دانلود منیجر": ["internet download manager", "idm", "free download manager"],
        "پلیر": ["vlc", "vlc media player", "media player", "potplayer"],
        "داکر": ["docker desktop", "docker"],
        "کلاد": ["claude"],
        "کورسر": ["cursor"],
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._catalog: dict[str, DiscoveredApplication] = {}
        self._last_scan: float = 0.0
        self._cache_ttl: float = 3600.0  # 1 hour
        self._init_builtins()

    def resolve_vscode_executable(self) -> Path | None:
        """Dynamically resolve Visual Studio Code executable across system, user, registry, and PATH."""
        import shutil

        # 1. Standard Program Files (System-wide install)
        for base in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            env_val = os.environ.get(base)
            if env_val:
                candidate = Path(env_val) / "Microsoft VS Code" / "Code.exe"
                if candidate.is_file():
                    return candidate.resolve()

        # 2. LocalAppData (Per-user install)
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            candidate = Path(local_app) / "Programs" / "Microsoft VS Code" / "Code.exe"
            if candidate.is_file():
                return candidate.resolve()

        # 3. Windows Registry App Paths
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(
                    root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\code.exe"
                ) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    p = Path(os.path.expandvars(str(val))).resolve()
                    if p.is_file():
                        return p
            except OSError:
                pass

        # 4. Search PATH for code.cmd, code.exe, or code
        which_code = shutil.which("code.cmd") or shutil.which("code.exe") or shutil.which("code")
        if which_code:
            p_which = Path(which_code).resolve()
            if p_which.suffix.lower() == ".exe" and p_which.is_file():
                return p_which
            for parent_dir in (p_which.parent.parent, p_which.parent):
                candidate_exe = parent_dir / "Code.exe"
                if candidate_exe.is_file():
                    return candidate_exe.resolve()

        # 5. Start Menu Shortcuts
        for env_k in ("APPDATA", "ALLUSERSPROFILE"):
            base_dir = os.environ.get(env_k)
            if base_dir:
                p_menu = Path(base_dir) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                if p_menu.is_dir():
                    for lnk in p_menu.rglob("*Visual Studio Code*.lnk"):
                        if lnk.is_file():
                            return lnk.resolve()

        return None

    def _init_builtins(self) -> None:
        """Seed essential Windows system applications."""
        vscode_p = self.resolve_vscode_executable()
        vscode_target = str(vscode_p) if vscode_p else "code.exe"

        builtins = [
            DiscoveredApplication(
                "notepad", "Notepad", "notepad.exe", "exe", ["notepad", "یادداشت"]
            ),
            DiscoveredApplication(
                "calc", "Calculator", "calc.exe", "exe", ["calc", "calculator", "ماشین حساب"]
            ),
            DiscoveredApplication(
                "explorer",
                "File Explorer",
                "explorer.exe",
                "exe",
                ["explorer", "file explorer", "اکسپلورر"],
            ),
            DiscoveredApplication(
                "cmd", "Command Prompt", "cmd.exe", "exe", ["cmd", "command prompt", "سی ام دی"]
            ),
            DiscoveredApplication(
                "wt",
                "Windows Terminal",
                "wt.exe",
                "exe",
                ["wt", "terminal", "windows terminal", "ترمینال"],
            ),
            DiscoveredApplication(
                "mspaint", "Paint", "mspaint.exe", "exe", ["paint", "mspaint", "نقاشی", "پینت"]
            ),
            DiscoveredApplication(
                "taskmgr",
                "Task Manager",
                "taskmgr.exe",
                "exe",
                ["taskmgr", "task manager", "تسک منیجر"],
            ),
            DiscoveredApplication(
                "msedge", "Microsoft Edge", "msedge.exe", "exe", ["edge", "msedge", "ادج", "اج"]
            ),
            DiscoveredApplication(
                "chrome", "Google Chrome", "chrome.exe", "exe", ["chrome", "google chrome", "کروم"]
            ),
            DiscoveredApplication(
                "code",
                "Visual Studio Code",
                vscode_target,
                "exe",
                ["code", "vscode", "visual studio code", "کد"],
            ),
        ]
        for app in builtins:
            self._catalog[app.app_id] = app

    def scan_applications(self, force_refresh: bool = False) -> dict[str, DiscoveredApplication]:
        """Discover applications across Windows registry, Start Menu, and Packaged apps."""
        now = time.time()
        with self._lock:
            if not force_refresh and self._catalog and (now - self._last_scan < self._cache_ttl):
                return self._catalog

            logger.info("Scanning Windows installed applications...")
            discovered: dict[str, DiscoveredApplication] = dict(self._catalog)

            # 1. Scan Registry App Paths
            self._scan_registry_app_paths(discovered)

            # 2. Scan Start Menu directories
            self._scan_start_menu_directories(discovered)

            # 3. Scan Packaged Apps via Get-StartApps
            self._scan_get_startapps(discovered)

            self._catalog = discovered
            self._last_scan = now
            logger.info(f"Discovered {len(self._catalog)} total Windows applications.")
            return self._catalog

    def _scan_registry_app_paths(self, catalog: dict[str, DiscoveredApplication]) -> None:
        """Scan HKLM and HKCU App Paths for registered executables."""
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                sub_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
                with winreg.OpenKey(root, sub_key) as key:
                    num_subkeys = winreg.QueryInfoKey(key)[0]
                    for i in range(num_subkeys):
                        try:
                            app_exe = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, app_exe) as app_key:
                                raw_path, _ = winreg.QueryValueEx(app_key, "")
                                if raw_path:
                                    clean_path = os.path.expandvars(str(raw_path).strip("\"';"))
                                    target_p = Path(clean_path)
                                    if target_p.is_file():
                                        base_name = target_p.stem
                                        app_id = re.sub(r"[^a-z0-9]", "", base_name.lower())
                                        if app_id and app_id not in catalog:
                                            catalog[app_id] = DiscoveredApplication(
                                                app_id=app_id,
                                                name=base_name,
                                                target=str(target_p),
                                                launch_type="exe",
                                                aliases=[base_name.lower(), app_exe.lower()],
                                            )
                        except OSError:
                            continue
            except OSError:
                continue

    def _scan_start_menu_directories(self, catalog: dict[str, DiscoveredApplication]) -> None:
        """Scan Start Menu folders for shortcuts."""
        search_dirs: list[Path] = []
        user_start = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs"
        if user_start.exists():
            search_dirs.append(user_start)

        common_start = (
            Path(os.environ.get("ALLUSERSPROFILE", r"C:\ProgramData"))
            / r"Microsoft\Windows\Start Menu\Programs"
        )
        if common_start.exists():
            search_dirs.append(common_start)

        for s_dir in search_dirs:
            try:
                for lnk in s_dir.rglob("*.lnk"):
                    stem = lnk.stem
                    # Skip uninstallers, help, and readmes
                    stem_lower = stem.lower()
                    if any(
                        x in stem_lower
                        for x in (
                            "uninstall",
                            "remove",
                            "help",
                            "readme",
                            "manual",
                            "license",
                            "website",
                        )
                    ):
                        continue

                    app_id = re.sub(r"[^a-z0-9]", "", stem_lower)
                    if app_id and app_id not in catalog:
                        catalog[app_id] = DiscoveredApplication(
                            app_id=app_id,
                            name=stem,
                            target=str(lnk),
                            launch_type="exe",  # Can be opened directly via os.startfile
                            aliases=[stem_lower],
                        )
            except Exception as exc:
                logger.debug(f"Start Menu scan error in {s_dir}: {exc}")

    def _scan_get_startapps(self, catalog: dict[str, DiscoveredApplication]) -> None:
        """Scan UWP and Desktop apps via PowerShell Get-StartApps."""
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-StartApps | ConvertTo-Json -Compress",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                if isinstance(data, dict):
                    data = [data]

                for item in data:
                    name = item.get("Name", "").strip()
                    app_id_raw = item.get("AppID", "").strip()
                    if not name or not app_id_raw:
                        continue

                    name_lower = name.lower()
                    if any(
                        x in name_lower
                        for x in (
                            "uninstall",
                            "help",
                            "faq",
                            "documentation",
                            "release notes",
                            "website",
                            "manual",
                        )
                    ):
                        continue

                    # Determine launch type
                    launch_type = "aumid"
                    target = app_id_raw
                    is_packaged = False

                    if (
                        app_id_raw.endswith(".exe")
                        or app_id_raw.endswith(".bat")
                        or app_id_raw.endswith(".cmd")
                    ):
                        launch_type = "exe"
                    elif "!" in app_id_raw or "." in app_id_raw:
                        launch_type = "aumid"
                        is_packaged = True

                    clean_id = re.sub(r"[^a-z0-9]", "", name_lower)
                    if clean_id:
                        # Add or update
                        existing = catalog.get(clean_id)
                        if not existing or not existing.is_packaged:
                            catalog[clean_id] = DiscoveredApplication(
                                app_id=clean_id,
                                name=name,
                                target=target,
                                launch_type=launch_type,
                                aliases=[name_lower],
                                is_packaged=is_packaged,
                            )
        except Exception as exc:
            logger.warning(f"Get-StartApps scan failed: {exc}")

    CATEGORY_NOISE_TOKENS: set[str] = {
        "app",
        "application",
        "program",
        "software",
        "tool",
        "client",
        "برنامه",
        "اپلیکیشن",
        "نرم‌افزار",
        "نرم",
        "افزار",
        "ابزار",
    }

    CODING_APP_PATTERNS: list[str] = [
        "visual studio code",
        "vscode",
        "code",
        "cursor",
        "antigravity ide",
        "antigravity",
        "pycharm",
        "intellij",
        "webstorm",
        "clion",
        "rider",
        "sublime",
        "notepad++",
        "atom",
        "opencode",
        "eclipse",
        "visual studio",
    ]

    SEMANTIC_CATEGORIES: dict[str, dict[str, Any]] = {
        "coding": {
            "keywords": [
                "coding",
                "code editor",
                "code",
                "ide",
                "programming",
                "developer environment",
                "development tool",
                "development environment",
                "need to code",
                "want to code",
                "start coding",
                "کدنویسی",
                "برنامه نویسی",
                "ادیتور کد",
                "محیط کدنویسی",
                "کد بزنم",
                "کد بزنیم",
                "وقت کدزدنه",
            ],
            "preferred": [
                "code",
                "vscode",
                "visual studio code",
                "cursor",
                "pycharm",
                "antigravity",
                "devenv",
            ],
        },
        "image_editing": {
            "keywords": [
                "edit an image",
                "edit image",
                "photo editor",
                "image editor",
                "edit photo",
                "paint a picture",
                "drawing tool",
                "draw something",
                "ویرایش عکس",
                "ادیت عکس",
                "عکس ویرایش",
                "عکس ادیت",
                "ویرایش تصویر",
                "ادیت تصویر",
                "تصویر ویرایش",
                "تصویر ادیت",
                "نقاشی",
                "ابزار طراحی",
            ],
            "preferred": ["mspaint", "paint", "photoshop", "gimp", "upscayl"],
        },
        "spreadsheet": {
            "keywords": [
                "spreadsheet",
                "spreadsheet application",
                "excel sheet",
                "sheet",
                "workbook",
                "صفحه گسترده",
                "اسپردشیت",
                "برنامه اکسل",
            ],
            "preferred": ["excel", "calc"],
        },
        "database": {
            "keywords": [
                "database",
                "database management",
                "database tool",
                "db tool",
                "db manager",
                "sql tool",
                "مدیریت دیتابیس",
                "ابزار دیتابیس",
                "پایگاه داده",
            ],
            "preferred": [
                "dbeaver",
                "pgadmin",
                "sqlitestudio",
                "mongodb compass",
                "datagrip",
                "heidisql",
            ],
        },
        "browser": {
            "keywords": [
                "web browser",
                "browser",
                "internet browser",
                "browse the web",
                "مرورگر",
                "مرورگر وب",
                "وب گردی",
            ],
            "preferred": ["chrome", "msedge", "brave", "firefox"],
        },
    }

    def find_application_by_category(
        self, query: str
    ) -> tuple[str | None, list[DiscoveredApplication]]:
        """Identify application category and return matching installed/discovered applications in preference order."""
        q = query.lower().strip()
        apps = self.scan_applications()

        for cat_name, cat_data in self.SEMANTIC_CATEGORIES.items():
            if any(kw in q for kw in cat_data["keywords"]):
                matched_apps: list[DiscoveredApplication] = []
                seen_ids: set[str] = set()

                # 1. First add preferred apps that are installed/discovered
                for pref_id in cat_data["preferred"]:
                    for app_id, app in apps.items():
                        app_str = f"{app.app_id} {app.name} {' '.join(app.aliases)}".lower()
                        if (pref_id == app_id or pref_id in app_str) and app.app_id not in seen_ids:
                            matched_apps.append(app)
                            seen_ids.add(app.app_id)

                return cat_name, matched_apps

        return None, []

    def is_generic_coding_request(self, query: str) -> bool:
        """Check whether user query asks for a coding application/environment generally."""
        q = query.lower().strip()
        coding_cues = (
            "coding",
            "code editor",
            "coding app",
            "coding application",
            "coding environment",
            "development tool",
            "development environment",
            "ide",
            "need to code",
            "want to code",
            "start coding",
            "start programming",
            "time to code",
            "open my code",
            "open coding",
            "programming",
            "برنامه کدنویسی",
            "محیط کدنویسی",
            "برنامه برای کد",
            "کدنویسی",
            "محیط برنامه نویسی",
            "برنامه برنامه‌نویسی",
            "برنامه نویسی",
            "برنامه‌نویسی",
            "کد بزنم",
            "کد بزنیم",
            "وقت کدزدنه",
            "بریم کد بزنیم",
            "شروع به کدنویسی",
            "میخوام کد بنویسم",
            "کدنویسی کنیم",
            "برنامه نویسی کنیم",
        )
        return any(c in q for c in coding_cues) and not any(
            specific in q
            for specific in (
                "vs code",
                "vscode",
                "cursor",
                "antigravity",
                "pycharm",
                "visual studio",
            )
        )

    def get_coding_applications(self) -> list[DiscoveredApplication]:
        """Return discovered software applications specifically designated for programming/coding."""
        apps = self.scan_applications()
        coding_apps: list[DiscoveredApplication] = []
        seen_ids: set[str] = set()

        for pattern in self.CODING_APP_PATTERNS:
            for app in apps.values():
                app_str = f"{app.name} {' '.join(app.aliases)}".lower()
                # Exclude installers and utilities like visual studio installer
                if "installer" in app_str or "uninstaller" in app_str:
                    continue
                if pattern in app_str and app.app_id not in seen_ids:
                    coding_apps.append(app)
                    seen_ids.add(app.app_id)

        return coding_apps

    def find_application(self, query: str) -> DiscoveredApplication | None:
        """Find the best matching application using exact, Persian alias, and fuzzy matching."""
        if not query or not query.strip():
            return None

        apps = self.scan_applications()
        q_norm = query.lower().strip()

        # 1. Check Persian alias mapping
        english_targets = []
        for fa_alias, en_names in self.PERSIAN_APP_ALIASES.items():
            if fa_alias in q_norm:
                english_targets.extend(en_names)

        # 2. Direct exact check
        q_clean = re.sub(r"[^a-z0-9]", "", q_norm)
        if q_clean in apps:
            return apps[q_clean]

        for app in apps.values():
            if q_norm == app.name.lower():
                return app
            if any(q_norm == a for a in app.aliases):
                return app

        # 3. Check English targets from Persian translation
        for target_name in english_targets:
            target_clean = re.sub(r"[^a-z0-9]", "", target_name)
            if target_clean in apps:
                return apps[target_clean]
            for app in apps.values():
                if target_name in app.name.lower() or any(target_name in a for a in app.aliases):
                    return app

        # If Persian query mapped to english targets, search using those targets too
        search_queries = [q_norm] + english_targets

        # 4. Substring and token match
        for sq in search_queries:
            tokens = [
                t
                for t in re.split(r"[\s\-_]+", sq)
                if len(t) > 2 and t not in self.CATEGORY_NOISE_TOKENS
            ]
            if not tokens:
                continue
            best_token_app: DiscoveredApplication | None = None
            max_token_score = 0

            for app in apps.values():
                app_str = f"{app.name} {' '.join(app.aliases)}".lower()
                score = sum(1 for t in tokens if t in app_str)
                if score > max_token_score:
                    max_token_score = score
                    best_token_app = app

            if max_token_score > 0 and best_token_app:
                return best_token_app

        # 5. Fuzzy string similarity matching (strict cutoff 0.7 to avoid false positives)
        candidate_names = {app.name.lower(): app for app in apps.values()}
        for sq in search_queries:
            matches = difflib.get_close_matches(sq, candidate_names.keys(), n=1, cutoff=0.7)
            if matches:
                return candidate_names[matches[0]]

        return None

    def launch(self, app: DiscoveredApplication) -> dict[str, Any]:
        """Launch a discovered application via native Win32 or shell:AppsFolder."""
        logger.info(
            f"Launching application: {app.name} (target: {app.target}, type: {app.launch_type})"
        )

        if app.launch_type == "aumid":
            # Launch packaged/UWP application
            os.startfile(f"shell:AppsFolder\\{app.target}")
            return {
                "status": "launched",
                "app_id": app.app_id,
                "name": app.name,
                "launch_type": "aumid",
                "target": app.target,
            }
        else:
            # Win32 executable or shortcut
            target_p = Path(app.target)
            if target_p.suffix.lower() == ".lnk":
                os.startfile(str(target_p))
            else:
                subprocess.Popen(str(target_p), shell=True)

            return {
                "status": "launched",
                "app_id": app.app_id,
                "name": app.name,
                "launch_type": "exe",
                "target": app.target,
            }


_app_discovery_instance: WindowsApplicationDiscovery | None = None


def get_windows_app_discovery() -> WindowsApplicationDiscovery:
    """Singleton getter for application discovery service."""
    global _app_discovery_instance
    if _app_discovery_instance is None:
        _app_discovery_instance = WindowsApplicationDiscovery()
    return _app_discovery_instance


def is_generic_coding_request(query: str) -> bool:
    """Check whether query asks for a coding application/environment generally."""
    return get_windows_app_discovery().is_generic_coding_request(query)


def get_coding_applications() -> list[DiscoveredApplication]:
    """Return discovered software applications specifically designated for programming/coding."""
    return get_windows_app_discovery().get_coding_applications()


def find_application_by_category(query: str) -> tuple[str | None, list[DiscoveredApplication]]:
    """Identify application category and return matching installed/discovered applications."""
    return get_windows_app_discovery().find_application_by_category(query)
