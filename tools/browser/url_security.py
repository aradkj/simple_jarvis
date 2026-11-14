"""URL security validation for JARVIS Phase 7 Browser Agent.

Implements strict URL validation with protections against:
- Dangerous URI schemes (file://, javascript:, data:, vbscript:, about:, blob:)
- Private/internal network addresses (RFC 1918, loopback, link-local)
- Cloud metadata endpoint (169.254.169.254)
- Embedded credentials (user:pass@host)
- DNS rebinding defenses via hostname resolution
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from infrastructure.logging import get_logger

logger = get_logger("browser.url_security")

# Schemes that are always blocked
_BLOCKED_SCHEMES: frozenset[str] = frozenset(
    {
        "file",
        "javascript",
        "data",
        "vbscript",
        "about",
        "blob",
        "ftp",
        "gopher",
    }
)

# Schemes that are allowed for navigation
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Private / reserved IPv4 networks
_PRIVATE_IPV4_NETWORKS: list[ipaddress.IPv4Network] = [
    ipaddress.IPv4Network("127.0.0.0/8"),  # Loopback
    ipaddress.IPv4Network("10.0.0.0/8"),  # Private Class A
    ipaddress.IPv4Network("172.16.0.0/12"),  # Private Class B
    ipaddress.IPv4Network("192.168.0.0/16"),  # Private Class C
    ipaddress.IPv4Network("169.254.0.0/16"),  # Link-local / APIPA
    ipaddress.IPv4Network("0.0.0.0/8"),  # "This" network
    ipaddress.IPv4Network("100.64.0.0/10"),  # Carrier-grade NAT
    ipaddress.IPv4Network("192.0.0.0/24"),  # IETF Protocol Assignments
    ipaddress.IPv4Network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.IPv4Network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.IPv4Network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.IPv4Network("224.0.0.0/4"),  # Multicast
    ipaddress.IPv4Network("240.0.0.0/4"),  # Reserved
    ipaddress.IPv4Network("255.255.255.255/32"),  # Broadcast
]

# Private / reserved IPv6 networks
_PRIVATE_IPV6_NETWORKS: list[ipaddress.IPv6Network] = [
    ipaddress.IPv6Network("::1/128"),  # Loopback
    ipaddress.IPv6Network("fe80::/10"),  # Link-local
    ipaddress.IPv6Network("fc00::/7"),  # Unique local
    ipaddress.IPv6Network("::ffff:127.0.0.0/104"),  # IPv4-mapped loopback
    ipaddress.IPv6Network("::ffff:10.0.0.0/104"),  # IPv4-mapped private
    ipaddress.IPv6Network("::ffff:172.16.0.0/108"),  # IPv4-mapped private
    ipaddress.IPv6Network("::ffff:192.168.0.0/112"),  # IPv4-mapped private
    ipaddress.IPv6Network("::ffff:169.254.0.0/112"),  # IPv4-mapped link-local
]

# Cloud metadata IP
_CLOUD_METADATA_IPS: frozenset[str] = frozenset(
    {
        "169.254.169.254",
        "fd00:ec2::254",
        "metadata.google.internal",
    }
)

# Cloud metadata hostnames
_CLOUD_METADATA_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "169.254.169.254",
    }
)

# Embedded credentials pattern
_CREDENTIALS_PATTERN = re.compile(r"[^/@]+:[^/@]+@")


@dataclass(frozen=True)
class ValidationResult:
    """Result of URL security validation."""

    is_valid: bool
    url: str
    normalized_url: str = ""
    rejection_reason: str = ""
    resolved_ip: str = ""
    details: dict[str, str] = field(default_factory=dict)


class URLSecurityValidator:
    """Validates URLs against security policies before browser navigation."""

    @staticmethod
    def validate_url(url: str, allow_localhost: bool = False) -> ValidationResult:
        """Validate a URL against the full security policy.

        Args:
            url: The URL string to validate.
            allow_localhost: If True, allows loopback addresses (testing only).

        Returns:
            ValidationResult with is_valid=True if safe, or rejection details.
        """
        if not url or not isinstance(url, str):
            return ValidationResult(
                is_valid=False,
                url=url or "",
                rejection_reason="URL is empty or not a string",
            )

        # Step 1: Normalize — decode percent-encoding, strip whitespace
        try:
            normalized = _normalize_url(url)
        except Exception as exc:
            return ValidationResult(
                is_valid=False,
                url=url,
                rejection_reason=f"URL normalization failed: {exc}",
            )

        # Step 2: Parse
        try:
            parsed = urlparse(normalized)
        except Exception as exc:
            return ValidationResult(
                is_valid=False,
                url=url,
                normalized_url=normalized,
                rejection_reason=f"URL parsing failed: {exc}",
            )

        # Step 3: Scheme validation
        scheme = (parsed.scheme or "").lower().strip()
        if not scheme:
            # Attempt to add https:// if missing
            normalized = f"https://{normalized}"
            parsed = urlparse(normalized)
            scheme = parsed.scheme

        if scheme in _BLOCKED_SCHEMES:
            return ValidationResult(
                is_valid=False,
                url=url,
                normalized_url=normalized,
                rejection_reason=f"Blocked URL scheme: '{scheme}://' is not allowed",
            )

        if scheme not in _ALLOWED_SCHEMES:
            return ValidationResult(
                is_valid=False,
                url=url,
                normalized_url=normalized,
                rejection_reason=f"Unsupported URL scheme: '{scheme}'. Only http:// and https:// are allowed",
            )

        # Step 4: Check for embedded credentials
        if parsed.username or parsed.password:
            return ValidationResult(
                is_valid=False,
                url=url,
                normalized_url=normalized,
                rejection_reason="URLs with embedded credentials (user:pass@host) are blocked",
            )
        # Also check the raw netloc for credential patterns
        netloc = parsed.netloc or ""
        if "@" in netloc and _CREDENTIALS_PATTERN.search(netloc):
            return ValidationResult(
                is_valid=False,
                url=url,
                normalized_url=normalized,
                rejection_reason="URLs with embedded credentials (user:pass@host) are blocked",
            )

        # Step 5: Hostname validation
        hostname = (parsed.hostname or "").lower().strip().rstrip(".")
        if not hostname:
            return ValidationResult(
                is_valid=False,
                url=url,
                normalized_url=normalized,
                rejection_reason="URL has no hostname",
            )

        # IDNA normalization for internationalized hostnames
        with contextlib.suppress(Exception):
            hostname = hostname.encode("idna").decode("ascii")

        # Check cloud metadata hostnames
        if (
            hostname in _CLOUD_METADATA_HOSTNAMES
            or hostname.rstrip(".") in _CLOUD_METADATA_HOSTNAMES
        ):
            return ValidationResult(
                is_valid=False,
                url=url,
                normalized_url=normalized,
                rejection_reason=f"Cloud metadata endpoint '{hostname}' is blocked (SSRF protection)",
            )

        # Step 6: Hostname looks like IP (including hex, dword, octal, short notation, IPv4-mapped IPv6)
        parsed_ip = _parse_any_ip(hostname)
        if parsed_ip is not None:
            ip_reason = _classify_ip(parsed_ip, allow_localhost)
            if ip_reason is not None:
                return ValidationResult(
                    is_valid=False,
                    url=url,
                    normalized_url=normalized,
                    rejection_reason=ip_reason,
                    resolved_ip=str(parsed_ip),
                )

        # Step 7: DNS resolution to detect private IPs behind public hostnames (checks all returned IPs)
        resolved_ips = _resolve_all_ips(hostname)
        for res_ip in resolved_ips:
            ip_result = _check_resolved_ip(res_ip, allow_localhost)
            if ip_result is not None:
                return ValidationResult(
                    is_valid=False,
                    url=url,
                    normalized_url=normalized,
                    rejection_reason=f"Hostname '{hostname}' resolves to blocked IP {res_ip}: {ip_result}",
                    resolved_ip=res_ip,
                )

        primary_ip = resolved_ips[0] if resolved_ips else ""
        logger.debug(f"URL validated: {normalized} -> {primary_ip or 'unresolved'}")

        return ValidationResult(
            is_valid=True,
            url=url,
            normalized_url=normalized,
            resolved_ip=primary_ip,
        )

    @staticmethod
    def validate_redirect_url(
        original_url: str,
        redirect_url: str,
        allow_localhost: bool = False,
    ) -> ValidationResult:
        """Validate a redirect target URL with the same security policy.

        Args:
            original_url: The original navigation URL (for logging).
            redirect_url: The redirect target URL to validate.
            allow_localhost: If True, allows loopback addresses.

        Returns:
            ValidationResult for the redirect target.
        """
        result = URLSecurityValidator.validate_url(redirect_url, allow_localhost=allow_localhost)
        if not result.is_valid:
            logger.warning(
                f"Redirect blocked: {original_url} -> {redirect_url}: {result.rejection_reason}"
            )
        return result


# --- Internal helpers ---


def _normalize_url(url: str) -> str:
    """Normalize a URL by decoding, stripping whitespace, removing null bytes, and normalizing unicode dots."""
    # Strip whitespace and null bytes
    url = url.strip().replace("\x00", "")

    # Normalize unicode / fullwidth dots to standard ASCII dot
    url = url.replace("\u3002", ".").replace("\uff0e", ".").replace("\uff61", ".")

    # Decode percent-encoding iteratively (handle double-encoding)
    prev = ""
    decoded = url
    for _ in range(5):  # Max 5 decode rounds to prevent infinite loops
        prev = decoded
        decoded = unquote(decoded)
        if decoded == prev:
            break

    # Collapse backslashes to forward slashes (Windows path confusion)
    decoded = decoded.replace("\\", "/")

    return decoded


def _parse_any_ip(
    hostname: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse dot-decimal, dword integer, hex, octal, or short-form IP representations."""
    clean_host = hostname.strip().rstrip(".")
    if clean_host.startswith("[") and clean_host.endswith("]"):
        clean_host = clean_host[1:-1]

    # 1. Standard ipaddress parser (IPv4 dot-decimal or standard IPv6)
    try:
        addr = ipaddress.ip_address(clean_host)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            return addr.ipv4_mapped
        return addr
    except ValueError:
        pass

    # 2. Integer dword representation (e.g. 2130706433 -> 127.0.0.1)
    if clean_host.isdigit():
        try:
            val = int(clean_host)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except (ValueError, OverflowError):
            pass

    # 3. Hex integer representation (e.g. 0x7f000001 -> 127.0.0.1)
    if clean_host.lower().startswith("0x"):
        try:
            val = int(clean_host, 16)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except (ValueError, OverflowError):
            pass

    # 4. Socket inet_aton parser (handles octal, hex parts, 127.1 short notation)
    try:
        parts = clean_host.split(".")
        if all(re.match(r"^(0x[0-9a-fA-F]+|0[0-7]*|[0-9]+)$", p) for p in parts):
            packed = socket.inet_aton(clean_host)
            return ipaddress.IPv4Address(packed)
    except OSError:
        pass

    return None


def _check_ip_direct(hostname: str, allow_localhost: bool) -> str | None:
    """Check if hostname is a literal IP and if it's private/blocked. Returns rejection reason or None."""
    addr = _parse_any_ip(hostname)
    if addr is None:
        return None  # Not an IP literal

    return _classify_ip(addr, allow_localhost)


def _check_resolved_ip(ip_str: str, allow_localhost: bool) -> str | None:
    """Check a resolved IP string against security rules."""
    try:
        addr = ipaddress.ip_address(ip_str)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
    except ValueError:
        return None
    return _classify_ip(addr, allow_localhost)


def _classify_ip(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_localhost: bool
) -> str | None:
    """Classify an IP address and return rejection reason if blocked, or None if allowed."""
    # Cloud metadata check
    if str(addr) in _CLOUD_METADATA_IPS:
        return f"Cloud metadata endpoint {addr} is blocked (SSRF protection)"

    if isinstance(addr, ipaddress.IPv4Address):
        # Loopback
        if addr.is_loopback and not allow_localhost:
            return f"Loopback address {addr} is blocked (set allow_localhost=True for testing)"
        if addr.is_loopback and allow_localhost:
            return None

        for net in _PRIVATE_IPV4_NETWORKS:
            if net == ipaddress.IPv4Network("127.0.0.0/8"):
                continue  # Already handled above
            if addr in net:
                return f"Private/reserved IPv4 address {addr} (in {net}) is blocked"

    elif isinstance(addr, ipaddress.IPv6Address):
        # Loopback
        if addr.is_loopback and not allow_localhost:
            return f"Loopback address {addr} is blocked (set allow_localhost=True for testing)"
        if addr.is_loopback and allow_localhost:
            return None

        for net in _PRIVATE_IPV6_NETWORKS:
            if net == ipaddress.IPv6Network("::1/128"):
                continue  # Already handled above
            if addr in net:
                return f"Private/reserved IPv6 address {addr} (in {net}) is blocked"

    return None


def _resolve_all_ips(hostname: str) -> list[str]:
    """Resolve hostname to all distinct IPv4 and IPv6 addresses."""
    clean_host = hostname.strip().rstrip(".")
    if clean_host.startswith("[") and clean_host.endswith("]"):
        clean_host = clean_host[1:-1]

    ips: list[str] = []
    try:
        results = socket.getaddrinfo(clean_host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for r in results:
            ip = r[4][0]
            if ip not in ips:
                ips.append(ip)
    except (socket.gaierror, OSError):
        pass
    return ips


def _resolve_hostname(hostname: str) -> str:
    """Resolve hostname to IP address for DNS rebinding defense. Returns IP string or empty."""
    ips = _resolve_all_ips(hostname)
    return ips[0] if ips else ""
