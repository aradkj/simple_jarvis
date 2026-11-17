"""Unit tests for Universal Application Category Discovery in JARVIS.

Tests mapping of natural-language categories (coding, image editing, spreadsheets,
database management, web browser) to installed applications with ranking and preference.
"""

from __future__ import annotations

import pytest

from tools.windows.discovery import (
    WindowsApplicationDiscovery,
    find_application_by_category,
    get_windows_app_discovery,
)


@pytest.fixture
def discovery() -> WindowsApplicationDiscovery:
    return get_windows_app_discovery()


def test_coding_category_discovery() -> None:
    """Natural-language coding intent resolves to coding category and editor."""
    queries = [
        "I need to do some coding",
        "Open a code editor",
        "کد بزنم",
        "محیط کدنویسی",
    ]
    for q in queries:
        cat, apps = find_application_by_category(q)
        assert cat == "coding", f"Failed to identify coding category for: {q}"
        assert len(apps) > 0
        app_names = [a.name.lower() for a in apps]
        assert any("code" in n or "cursor" in n or "antigravity" in n for n in app_names)


def test_image_editing_category_discovery() -> None:
    """Natural-language image editing intent resolves to image editing category and Paint."""
    queries = [
        "I want to edit an image",
        "Open an image editor",
        "میخوام عکس ویرایش کنم",
        "ادیت تصویر",
    ]
    for q in queries:
        cat, apps = find_application_by_category(q)
        assert cat == "image_editing", f"Failed to identify image_editing category for: {q}"
        assert len(apps) > 0
        top_app = apps[0]
        assert "paint" in top_app.name.lower() or "paint" in top_app.app_id.lower()


def test_spreadsheet_category_discovery() -> None:
    """Natural-language spreadsheet intent resolves to spreadsheet category."""
    queries = [
        "Open a spreadsheet application",
        "اسپردشیت",
        "برنامه اکسل",
    ]
    for q in queries:
        cat, apps = find_application_by_category(q)
        assert cat == "spreadsheet", f"Failed to identify spreadsheet category for: {q}"


def test_database_category_discovery() -> None:
    """Natural-language database management intent resolves to database category."""
    queries = [
        "Launch database management tool",
        "ابزار مدیریت دیتابیس",
    ]
    for q in queries:
        cat, apps = find_application_by_category(q)
        assert cat == "database", f"Failed to identify database category for: {q}"


def test_browser_category_discovery() -> None:
    """Natural-language browser intent resolves to browser category and web browser."""
    queries = [
        "Open a web browser",
        "مرورگر وب",
    ]
    for q in queries:
        cat, apps = find_application_by_category(q)
        assert cat == "browser", f"Failed to identify browser category for: {q}"
        assert len(apps) > 0
        top_app = apps[0]
        assert any(b in top_app.name.lower() for b in ("chrome", "edge", "brave", "firefox"))
