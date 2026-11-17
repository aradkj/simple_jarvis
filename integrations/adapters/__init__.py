"""Foundation Adapters for JARVIS Universal Integration Hub."""

from integrations.adapters.browser_adapter import BrowserIntegration
from integrations.adapters.filesystem_adapter import FilesystemIntegration
from integrations.adapters.github_adapter import GitHubIntegration
from integrations.adapters.windows_adapter import WindowsIntegration

__all__ = [
    "GitHubIntegration",
    "WindowsIntegration",
    "FilesystemIntegration",
    "BrowserIntegration",
]
