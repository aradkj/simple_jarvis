"""Automated UI Screenshot Generation Script for JARVIS Certification Report."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath("."))

from PySide6.QtWidgets import QApplication, QScrollArea

from ui.main_window import MainWindow, SettingsDialog
from ui.visualizer import JarvisVisualizerWidget


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    os.makedirs("docs/screenshots", exist_ok=True)

    agent = MagicMock()
    agent.voice_pipeline = MagicMock()
    agent.voice_pipeline.state.value = "idle"
    agent.voice_pipeline.is_conversation_mode = False
    agent.voice_pipeline.get_active_input_device_name.return_value = (
        "Microphone Array (Realtek Audio)"
    )

    win = MainWindow(agent=agent)
    win.resize(1280, 800)
    win.show()
    app.processEvents()

    # 1. Main UI Idle Standby
    pix1 = win.grab()
    pix1.save("docs/screenshots/jarvis_ui_main_idle.png")
    print("Saved: jarvis_ui_main_idle.png")

    # 2. Main UI Listening in Continuous Conversation Mode
    win.visualizer.set_voice_state("listening")
    win.visualizer.set_mic_level(0.72)
    win.voice_conv_btn.setText("⏹️ End Conversation")
    win.voice_status_lbl.setText("🎙️ Conversation Mode Active (Listening...)")
    app.processEvents()
    pix2 = win.grab()
    pix2.save("docs/screenshots/jarvis_ui_voice_listening.png")
    print("Saved: jarvis_ui_voice_listening.png")

    # 3. Main UI Speaking British Voice
    win.visualizer.set_voice_state("speaking")
    win.voice_status_lbl.setText("Speaking (George - British English Neural)...")
    app.processEvents()
    pix3 = win.grab()
    pix3.save("docs/screenshots/jarvis_ui_voice_speaking.png")
    print("Saved: jarvis_ui_voice_speaking.png")

    # 4. Standalone Visualizer Comparison
    viz = JarvisVisualizerWidget()
    viz.resize(750, 160)
    viz.show()

    viz.set_voice_state("speaking")
    app.processEvents()
    viz.grab().save("docs/screenshots/jarvis_visualizer_speaking.png")

    viz.set_voice_state("interrupted")
    app.processEvents()
    viz.grab().save("docs/screenshots/jarvis_visualizer_interrupted.png")

    viz.set_voice_state("recording")
    viz.set_mic_level(0.85)
    app.processEvents()
    viz.grab().save("docs/screenshots/jarvis_visualizer_recording.png")
    print("Saved visualizer states.")

    # 5. Settings Dialog with Voice Settings Scrolled into View
    dlg = SettingsDialog(win.settings, win)
    dlg.resize(800, 750)
    dlg.show()
    app.processEvents()

    scroll_area = dlg.findChild(QScrollArea)
    if scroll_area:
        vbar = scroll_area.verticalScrollBar()
        vbar.setValue(vbar.maximum())
        app.processEvents()

    pix_dlg = dlg.grab()
    pix_dlg.save("docs/screenshots/jarvis_ui_settings_voice.png")
    print("Saved: jarvis_ui_settings_voice.png")

    print("All UI screenshots successfully generated.")


if __name__ == "__main__":
    main()
