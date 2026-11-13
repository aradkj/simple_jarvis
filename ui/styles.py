"""Theme definitions, color palettes, and Qt stylesheets for JARVIS."""

DARK_THEME_QSS = """
/* JARVIS Modern Futuristic Dark Theme */

QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: "Segoe UI", Tahoma, "Vazirmatn", Arial, sans-serif;
    font-size: 13px;
    selection-background-color: #1f6feb;
    selection-color: #ffffff;
}

QMainWindow {
    background-color: #0b0f14;
}

/* ScrollBars */
QScrollBar:vertical {
    border: none;
    background: #0d1117;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #30363d;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #58a6ff;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Chat Input Field */
QPlainTextEdit, QTextEdit, QLineEdit {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 8px 12px;
    color: #f0f6fc;
}

QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {
    border: 1px solid #58a6ff;
    background-color: #1c2129;
}

/* Buttons */
QPushButton {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 600;
    color: #c9d1d9;
}

QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #161b22;
}

QPushButton:disabled {
    background-color: #161b22;
    border-color: #21262d;
    color: #484f58;
}

/* Primary Action Button (Futuristic Cyan/Blue Accent) */
QPushButton#PrimaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1f6feb, stop:1 #00d2ff);
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-weight: 600;
}

QPushButton#PrimaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #388bfd, stop:1 #33dcff);
}

QPushButton#PrimaryButton:pressed {
    background: #1f6feb;
}

/* Status Cards & Frames */
QFrame#StatusCard {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 12px;
}

QFrame#HeaderCard {
    background-color: #11161d;
    border-bottom: 1px solid #21262d;
}

/* Labels */
QLabel {
    background: transparent;
}

QLabel#CardTitle {
    font-size: 11px;
    font-weight: 700;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 1px;
}

QLabel#CardValue {
    font-size: 14px;
    font-weight: 600;
    color: #58a6ff;
}

QLabel#AppTitle {
    font-size: 18px;
    font-weight: 800;
    color: #00d2ff;
    letter-spacing: 2px;
}

QLabel#AppSubtitle {
    font-size: 12px;
    color: #8b949e;
}
"""


def is_persian_text(text: str) -> bool:
    """Detect if a text segment predominantly contains Persian/Arabic unicode characters."""
    for ch in text:
        # Arabic & Persian Unicode ranges
        if (
            "\u0600" <= ch <= "\u06ff"
            or "\u0750" <= ch <= "\u077f"
            or "\u08a0" <= ch <= "\u08ff"
            or "\ufb50" <= ch <= "\ufdff"
            or "\ufe70" <= ch <= "\ufeff"
        ):
            return True
    return False
