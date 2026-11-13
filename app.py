"""JARVIS Personal AI Desktop Agent Application Entry Point."""

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from config import get_settings
from core.agent import JARVISAgent
from infrastructure.logging import get_logger, setup_logging
from infrastructure.network import configure_system_proxy
from ui.main_window import MainWindow

logger = get_logger("app")


def main() -> int:
    """Initialize subsystems, construct the Qt application, and run the event loop."""
    try:
        # 0. Configure system proxy for cloud AI endpoints
        configure_system_proxy()

        # 1. Load Configuration
        settings = get_settings()

        # 2. Setup Centralized Logging
        setup_logging(
            log_level=settings.log_level,
            log_to_file=True,
        )
        logger.info(
            f"Starting {settings.app_name} v{settings.app_version} "
            f"(env={settings.app_env}, lang={settings.app_language})"
        )

        # 3. Create Qt Application
        app = QApplication(sys.argv)
        app.setApplicationName(settings.app_name)
        app.setApplicationVersion(settings.app_version)

        # 4. Initialize Core Agent
        agent = JARVISAgent(settings=settings)
        agent.initialize()

        # 5. Create Main Application Window
        window = MainWindow(agent=agent, settings=settings)
        window.show()

        # 6. Allow Python signal processing (e.g. Ctrl+C in terminal)
        signal.signal(signal.SIGINT, lambda *args: app.quit())
        timer = QTimer()
        timer.timeout.connect(lambda: None)
        timer.start(500)

        # 7. Connect aboutToQuit for clean shutdown
        app.aboutToQuit.connect(agent.shutdown)

        logger.info("Application event loop started.")
        exit_code = app.exec()
        logger.info(f"Application exited with code {exit_code}")
        return exit_code

    except Exception as exc:
        # Graceful startup error handling
        logger.critical(f"Fatal error during application startup: {exc}", exc_info=True)
        print(f"[FATAL ERROR] Failed to start JARVIS: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
