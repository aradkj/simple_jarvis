"""Google Antigravity IDE Integration & Lifecycle Hook Manager."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("antigravity_ide")


class AntigravityIDEManager:
    """Manages Antigravity IDE discovery, configuration, and lifecycle hook integration."""

    KNOWN_IDE_EXECUTABLES = [
        Path(os.path.expanduser("~"))
        / "AppData"
        / "Local"
        / "Programs"
        / "Antigravity IDE"
        / "Antigravity IDE.exe",
        Path(os.path.expanduser("~"))
        / "AppData"
        / "Local"
        / "Programs"
        / "antigravity"
        / "Antigravity.exe",
        Path("C:/Program Files/Antigravity IDE/Antigravity IDE.exe"),
    ]

    GLOBAL_CONFIG_DIR = Path(os.path.expanduser("~")) / ".gemini" / "config"
    GLOBAL_HOOKS_FILE = GLOBAL_CONFIG_DIR / "hooks.json"
    GLOBAL_HOOKS_BAK = GLOBAL_CONFIG_DIR / "hooks.json.bak"

    JARVIS_HOOK_MARKER = "__jarvis_hook__"

    def __init__(self) -> None:
        self.bridge_script_path = Path(__file__).parent / "bridge_receiver.py"
        self._ensure_bridge_script()

    def _ensure_bridge_script(self) -> None:
        """Create the lightweight bridge receiver script called by Antigravity IDE hooks."""
        if not self.bridge_script_path.exists():
            content = '''"""JARVIS Bridge Receiver for Antigravity IDE Lifecycle Hooks."""
import sys
import json
import os
from pathlib import Path

def main():
    try:
        raw_input = sys.stdin.read()
        payload = json.loads(raw_input) if raw_input.strip() else {}
    except Exception:
        payload = {"raw": raw_input}

    event_name = sys.argv[1] if len(sys.argv) > 1 else "Unknown"

    # Store event in temp hook drop directory
    drop_dir = Path(os.path.expanduser("~")) / ".gemini" / "jarvis_hooks_events"
    drop_dir.mkdir(parents=True, exist_ok=True)

    event_file = drop_dir / f"event_{int(os.times().elapsed * 1000)}.json"
    with open(event_file, "w", encoding="utf-8") as f:
        json.dump({"event": event_name, "payload": payload}, f, indent=2)

if __name__ == "__main__":
    main()
'''
            try:
                self.bridge_script_path.write_text(content, encoding="utf-8")
            except Exception as exc:
                logger.debug(f"Could not write bridge script: {exc}")

    def discover_ide(self) -> dict[str, Any]:
        """Detect Antigravity IDE installation and executable path."""
        for p in self.KNOWN_IDE_EXECUTABLES:
            if p.is_file():
                return {
                    "installed": True,
                    "executable_path": str(p.resolve()),
                    "version": "Antigravity IDE 2.x",
                }
        return {
            "installed": False,
            "executable_path": None,
            "version": None,
        }

    def get_hooks_status(self, workspace_path: str | Path | None = None) -> dict[str, Any]:
        """Inspect hook configuration globally or inside a workspace."""
        hooks_file = self._resolve_hooks_file(workspace_path)
        if not hooks_file.exists():
            return {
                "hooks_file": str(hooks_file),
                "exists": False,
                "jarvis_hooks_installed": False,
                "configured_hooks": {},
            }

        try:
            with open(hooks_file, encoding="utf-8") as f:
                data = json.load(f)
            hooks = data.get("hooks", {})
            jarvis_installed = False
            for _event_name, hook_list in hooks.items():
                if isinstance(hook_list, list):
                    for h in hook_list:
                        if isinstance(h, dict) and self.JARVIS_HOOK_MARKER in h.get("name", ""):
                            jarvis_installed = True
                            break

            return {
                "hooks_file": str(hooks_file),
                "exists": True,
                "jarvis_hooks_installed": jarvis_installed,
                "configured_hooks": list(hooks.keys()),
            }
        except Exception as exc:
            return {
                "hooks_file": str(hooks_file),
                "exists": True,
                "error": str(exc),
                "jarvis_hooks_installed": False,
            }

    def install_hooks(self, workspace_path: str | Path | None = None) -> bool:
        """Safely merge JARVIS lifecycle hooks with automatic backup."""
        hooks_file = self._resolve_hooks_file(workspace_path)
        hooks_dir = hooks_file.parent
        hooks_dir.mkdir(parents=True, exist_ok=True)

        existing_data: dict[str, Any] = {}
        if hooks_file.exists():
            bak_file = hooks_dir / f"{hooks_file.name}.bak"
            try:
                shutil.copy2(hooks_file, bak_file)
                logger.info(f"Backed up hooks file to {bak_file}")
                with open(hooks_file, encoding="utf-8") as f:
                    existing_data = json.load(f)
            except Exception as exc:
                logger.warning(f"Error reading or backing up existing hooks file: {exc}")

        if "hooks" not in existing_data or not isinstance(existing_data["hooks"], dict):
            existing_data["hooks"] = {}

        python_exe = sys.executable
        bridge_script = str(self.bridge_script_path.resolve())

        # Target lifecycle events: Stop, SessionStart, PostInvocation
        monitored_events = ["Stop", "SessionStart", "PostInvocation"]

        for ev in monitored_events:
            ev_list = existing_data["hooks"].setdefault(ev, [])
            # Filter out existing jarvis hook if present to avoid duplication
            filtered = [
                h
                for h in ev_list
                if not (isinstance(h, dict) and self.JARVIS_HOOK_MARKER in h.get("name", ""))
            ]
            # Add JARVIS hook
            filtered.append(
                {
                    "name": f"{self.JARVIS_HOOK_MARKER}_{ev}",
                    "command": f'"{python_exe}" "{bridge_script}" {ev}',
                    "timeout": 15,
                }
            )
            existing_data["hooks"][ev] = filtered

        try:
            with open(hooks_file, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, indent=2)
            logger.info(f"Successfully installed JARVIS lifecycle hooks into {hooks_file}")
            return True
        except Exception as exc:
            logger.error(f"Failed to write hooks file: {exc}")
            return False

    def uninstall_hooks(self, workspace_path: str | Path | None = None) -> bool:
        """Safely remove JARVIS lifecycle hooks and restore backup if appropriate."""
        hooks_file = self._resolve_hooks_file(workspace_path)
        if not hooks_file.exists():
            return True

        bak_file = hooks_file.parent / f"{hooks_file.name}.bak"
        try:
            with open(hooks_file, encoding="utf-8") as f:
                data = json.load(f)

            hooks = data.get("hooks", {})
            for ev, hook_list in list(hooks.items()):
                if isinstance(hook_list, list):
                    filtered = [
                        h
                        for h in hook_list
                        if not (
                            isinstance(h, dict) and self.JARVIS_HOOK_MARKER in h.get("name", "")
                        )
                    ]
                    if filtered:
                        hooks[ev] = filtered
                    else:
                        del hooks[ev]

            with open(hooks_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            logger.info(f"Successfully removed JARVIS hooks from {hooks_file}")
            return True
        except Exception as exc:
            logger.error(f"Error removing hooks: {exc}")
            if bak_file.exists():
                shutil.copy2(bak_file, hooks_file)
                logger.info(f"Restored backup hooks from {bak_file}")
                return True
            return False

    def _resolve_hooks_file(self, workspace_path: str | Path | None) -> Path:
        if workspace_path:
            ws_agents = Path(workspace_path) / ".agents" / "hooks.json"
            return ws_agents
        return self.GLOBAL_HOOKS_FILE
