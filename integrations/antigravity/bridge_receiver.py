"""JARVIS Bridge Receiver for Antigravity IDE Lifecycle Hooks."""

import json
import os
import sys
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
