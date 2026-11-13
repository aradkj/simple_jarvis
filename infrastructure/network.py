"""Network utilities, Windows system proxy discovery, and connectivity helpers."""

from __future__ import annotations

import os
import socket
import urllib.request
from urllib.parse import urlparse

from infrastructure.logging import get_logger

logger = get_logger("infrastructure.network")


def is_proxy_alive(proxy_url: str, timeout_sec: float = 0.5) -> bool:
    """Test if a proxy endpoint is currently listening and accepting connections."""
    try:
        parsed = urlparse(proxy_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except Exception:
        return False


def configure_system_proxy() -> None:
    """Auto-detect Windows system proxy and propagate to environment for httpx/requests if alive."""
    try:
        proxies = urllib.request.getproxies()
        http_val = proxies.get("http")
        https_val = proxies.get("https") or http_val

        active_proxy = None
        if https_val and is_proxy_alive(https_val):
            active_proxy = https_val
        elif http_val and is_proxy_alive(http_val):
            active_proxy = http_val

        if active_proxy:
            for var in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
                if var not in os.environ or not os.environ[var].strip():
                    os.environ[var] = active_proxy
            logger.info(f"Configured active system proxy for HTTP/HTTPS: {active_proxy}")
    except Exception as exc:
        logger.debug(f"System proxy auto-detection skipped: {exc}")
