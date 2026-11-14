"""Unit test suite for Phase 7 URL security validation and SSRF defenses."""

from tools.browser.url_security import URLSecurityValidator


class TestURLSecurityValidator:
    """Test suite for URLSecurityValidator across schemes, IP ranges, and encoding tricks."""

    # --- Valid URL Tests ---

    def test_valid_https_url(self) -> None:
        result = URLSecurityValidator.validate_url("https://example.com/path?q=1")
        assert result.is_valid is True
        assert result.rejection_reason == ""

    def test_valid_http_url(self) -> None:
        result = URLSecurityValidator.validate_url("http://example.org/about")
        assert result.is_valid is True

    def test_valid_subdomain_url(self) -> None:
        result = URLSecurityValidator.validate_url("https://sub.domain.example.com/api/v1")
        assert result.is_valid is True

    def test_valid_url_with_port(self) -> None:
        result = URLSecurityValidator.validate_url("https://example.com:8443/secure")
        assert result.is_valid is True

    def test_valid_url_missing_scheme_defaults_to_https(self) -> None:
        result = URLSecurityValidator.validate_url("example.com/index.html")
        assert result.is_valid is True
        assert result.normalized_url.startswith("https://")

    # --- Blocked Scheme Tests ---

    def test_file_scheme_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("file:///C:/Windows/System32/calc.exe")
        assert result.is_valid is False
        assert "file" in result.rejection_reason.lower()

    def test_file_scheme_linux_style_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("file:///etc/passwd")
        assert result.is_valid is False
        assert "file" in result.rejection_reason.lower()

    def test_javascript_scheme_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("javascript:alert(document.cookie)")
        assert result.is_valid is False
        assert "javascript" in result.rejection_reason.lower()

    def test_javascript_case_insensitive_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("JavaScript:void(0)")
        assert result.is_valid is False
        assert "javascript" in result.rejection_reason.lower()

    def test_data_scheme_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("data:text/html,<script>alert(1)</script>")
        assert result.is_valid is False
        assert "data" in result.rejection_reason.lower()

    def test_vbscript_scheme_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("vbscript:MsgBox('XSS')")
        assert result.is_valid is False
        assert "vbscript" in result.rejection_reason.lower()

    def test_about_scheme_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("about:config")
        assert result.is_valid is False

    def test_blob_scheme_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("blob:https://example.com/uuid-here")
        assert result.is_valid is False

    def test_ftp_scheme_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("ftp://ftp.example.com/file.txt")
        assert result.is_valid is False

    def test_gopher_scheme_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("gopher://gopher.example.com")
        assert result.is_valid is False

    # --- Private and Loopback IP Tests ---

    def test_ipv4_loopback_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://127.0.0.1:8080")
        assert result.is_valid is False
        assert "loopback" in result.rejection_reason.lower()

    def test_ipv4_loopback_subnet_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://127.0.1.5:3000")
        assert result.is_valid is False

    def test_localhost_hostname_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://localhost:5000/api")
        assert result.is_valid is False

    def test_ipv6_loopback_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://[::1]:8000")
        assert result.is_valid is False

    def test_ipv4_class_a_private_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://10.0.0.1/admin")
        assert result.is_valid is False
        assert "private" in result.rejection_reason.lower()

    def test_ipv4_class_b_private_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://172.16.0.50/dashboard")
        assert result.is_valid is False
        assert "private" in result.rejection_reason.lower()

    def test_ipv4_class_c_private_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://192.168.1.1/router")
        assert result.is_valid is False
        assert "private" in result.rejection_reason.lower()

    def test_link_local_apipa_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://169.254.1.1/internal")
        assert result.is_valid is False

    def test_ipv6_link_local_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://[fe80::1]/service")
        assert result.is_valid is False

    def test_carrier_grade_nat_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://100.64.0.1")
        assert result.is_valid is False

    # --- Cloud Metadata Endpoint Tests (SSRF Protection) ---

    def test_aws_gcp_metadata_ip_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://169.254.169.254/latest/meta-data/")
        assert result.is_valid is False
        assert "metadata" in result.rejection_reason.lower()

    def test_gcp_metadata_internal_hostname_blocked(self) -> None:
        result = URLSecurityValidator.validate_url(
            "http://metadata.google.internal/computeMetadata/v1/"
        )
        assert result.is_valid is False
        assert "metadata" in result.rejection_reason.lower()

    def test_gcp_metadata_goog_hostname_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://metadata.goog/")
        assert result.is_valid is False
        assert "metadata" in result.rejection_reason.lower()

    def test_ipv6_metadata_ip_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("http://[fd00:ec2::254]/latest/meta-data/")
        assert result.is_valid is False
        assert "metadata" in result.rejection_reason.lower()

    # --- Embedded Credentials Tests ---

    def test_embedded_credentials_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("https://admin:secret@example.com/dashboard")
        assert result.is_valid is False
        assert "credential" in result.rejection_reason.lower()

    def test_embedded_user_only_blocked(self) -> None:
        result = URLSecurityValidator.validate_url("https://root:password@1.2.3.4/")
        assert result.is_valid is False

    # --- Obfuscation and Encoding Bypass Tests ---

    def test_percent_encoded_javascript_scheme_blocked(self) -> None:
        # %6A%61%76%61%73%63%72%69%70%74%3A is 'javascript:'
        result = URLSecurityValidator.validate_url("%6A%61%76%61%73%63%72%69%70%74%3Aalert(1)")
        assert result.is_valid is False

    def test_double_encoded_scheme_blocked(self) -> None:
        # %256A is double-encoded 'j'
        result = URLSecurityValidator.validate_url("%256Aavascript:alert(1)")
        assert result.is_valid is False

    def test_null_bytes_stripped_and_validated(self) -> None:
        result = URLSecurityValidator.validate_url("file\x00://etc/passwd")
        assert result.is_valid is False

    def test_backslash_normalized(self) -> None:
        result = URLSecurityValidator.validate_url("file:\\\\C:\\Windows\\win.ini")
        assert result.is_valid is False

    # --- Empty and Malformed Input Tests ---

    def test_empty_url_rejected(self) -> None:
        result = URLSecurityValidator.validate_url("")
        assert result.is_valid is False
        assert "empty" in result.rejection_reason.lower()

    def test_whitespace_only_url_rejected(self) -> None:
        result = URLSecurityValidator.validate_url("   \t\n  ")
        assert result.is_valid is False

    def test_none_url_rejected(self) -> None:
        result = URLSecurityValidator.validate_url(None)  # type: ignore
        assert result.is_valid is False

    # --- Testing Mode Localhost Allowance ---

    def test_allow_localhost_in_testing_mode(self) -> None:
        result = URLSecurityValidator.validate_url(
            "http://127.0.0.1:8080/test", allow_localhost=True
        )
        assert result.is_valid is True

    def test_allow_localhost_name_in_testing_mode(self) -> None:
        result = URLSecurityValidator.validate_url("http://localhost:9000/", allow_localhost=True)
        assert result.is_valid is True

    def test_allow_localhost_still_blocks_cloud_metadata(self) -> None:
        # Even if allow_localhost=True, cloud metadata 169.254.169.254 must REMAIN blocked!
        result = URLSecurityValidator.validate_url("http://169.254.169.254/", allow_localhost=True)
        assert result.is_valid is False
        assert "metadata" in result.rejection_reason.lower()

    def test_allow_localhost_still_blocks_file_scheme(self) -> None:
        result = URLSecurityValidator.validate_url("file:///etc/hosts", allow_localhost=True)
        assert result.is_valid is False

    # --- Redirect Validation Tests ---

    def test_safe_redirect_allowed(self) -> None:
        result = URLSecurityValidator.validate_redirect_url(
            original_url="https://example.com",
            redirect_url="https://example.com/welcome",
        )
        assert result.is_valid is True

    def test_malicious_redirect_to_internal_ip_blocked(self) -> None:
        result = URLSecurityValidator.validate_redirect_url(
            original_url="https://example.com/redirect?to=192.168.1.1",
            redirect_url="http://192.168.1.1/admin",
        )
        assert result.is_valid is False
        assert "private" in result.rejection_reason.lower()

    def test_malicious_redirect_to_metadata_blocked(self) -> None:
        result = URLSecurityValidator.validate_redirect_url(
            original_url="https://example.com/ssrf",
            redirect_url="http://169.254.169.254/latest/user-data",
        )
        assert result.is_valid is False
        assert "metadata" in result.rejection_reason.lower()

    # --- Advanced SSRF, Alternative IP, and DNS Rebinding Tests ---

    def test_dword_ip_representation_blocked(self) -> None:
        """Dword integer 2130706433 (127.0.0.1) is recognized and blocked."""
        result = URLSecurityValidator.validate_url("http://2130706433/")
        assert result.is_valid is False
        assert any(k in result.rejection_reason.lower() for k in ("loopback", "private", "blocked"))

    def test_hex_ip_representation_blocked(self) -> None:
        """Hex integer 0x7f000001 (127.0.0.1) is recognized and blocked."""
        result = URLSecurityValidator.validate_url("http://0x7f000001/")
        assert result.is_valid is False
        assert any(k in result.rejection_reason.lower() for k in ("loopback", "private", "blocked"))

    def test_octal_ip_representation_blocked(self) -> None:
        """Octal IP 0177.0.0.1 (127.0.0.1) is recognized and blocked."""
        result = URLSecurityValidator.validate_url("http://0177.0.0.1/")
        assert result.is_valid is False
        assert any(k in result.rejection_reason.lower() for k in ("loopback", "private", "blocked"))

    def test_short_form_ip_representation_blocked(self) -> None:
        """Short-form IP representations like 127.1 and 10.1 are recognized and blocked."""
        res_127 = URLSecurityValidator.validate_url("http://127.1/")
        assert res_127.is_valid is False
        assert any(
            k in res_127.rejection_reason.lower() for k in ("loopback", "private", "blocked")
        )

        res_10 = URLSecurityValidator.validate_url("http://10.1/")
        assert res_10.is_valid is False
        assert any(k in res_10.rejection_reason.lower() for k in ("private", "blocked"))

    def test_ipv4_mapped_ipv6_loopback_blocked(self) -> None:
        """IPv4-mapped IPv6 address [::ffff:127.0.0.1] is recognized and blocked."""
        result = URLSecurityValidator.validate_url("http://[::ffff:127.0.0.1]/")
        assert result.is_valid is False
        assert any(k in result.rejection_reason.lower() for k in ("loopback", "private", "blocked"))

    def test_ipv4_mapped_ipv6_metadata_blocked(self) -> None:
        """IPv4-mapped IPv6 metadata address [::ffff:a9fe:a9fe] is recognized and blocked."""
        result = URLSecurityValidator.validate_url("http://[::ffff:a9fe:a9fe]/")
        assert result.is_valid is False
        assert any(k in result.rejection_reason.lower() for k in ("metadata", "blocked"))

    def test_trailing_dot_metadata_blocked(self) -> None:
        """Trailing-dot metadata hostnames are normalized and blocked."""
        res_ip = URLSecurityValidator.validate_url("http://169.254.169.254./")
        assert res_ip.is_valid is False
        assert "metadata" in res_ip.rejection_reason.lower()

        res_host = URLSecurityValidator.validate_url("http://metadata.google.internal./")
        assert res_host.is_valid is False
        assert "metadata" in res_host.rejection_reason.lower()

    def test_trailing_dot_localhost_blocked(self) -> None:
        """Trailing-dot localhost hostname is normalized and blocked."""
        result = URLSecurityValidator.validate_url("http://localhost./")
        assert result.is_valid is False
        assert any(k in result.rejection_reason.lower() for k in ("loopback", "blocked"))

    def test_unicode_fullwidth_dot_normalized_and_blocked(self) -> None:
        """Unicode ideographic full stop (\u3002) is normalized to ASCII dot and blocked."""
        result = URLSecurityValidator.validate_url("http://127\u30020\u30020\u30021/")
        assert result.is_valid is False
        assert any(k in result.rejection_reason.lower() for k in ("loopback", "private", "blocked"))

    def test_multi_ip_dns_resolution_private_blocked(self, monkeypatch) -> None:
        """If a hostname resolves to both a public IP and a private IP, it must be rejected."""
        import socket

        def mock_getaddrinfo(host, port, family=0, socktype=0):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
        result = URLSecurityValidator.validate_url("https://dual-stack-rebind.com")
        assert result.is_valid is False
        assert "127.0.0.1" in result.rejection_reason

    def test_dns_rebinding_result_changing_blocked(self, monkeypatch) -> None:
        """Simulate DNS rebinding where resolution changes to private IP on subsequent connection."""
        import socket

        # Call 1: initial check -> returns private IP
        def mock_getaddrinfo(host, port, family=0, socktype=0):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
        result = URLSecurityValidator.validate_url("https://fast-rebind.attacker.com")
        assert result.is_valid is False
        assert "10.0.0.1" in result.rejection_reason

    def test_redirect_to_ipv6_loopback_blocked(self) -> None:
        """Redirect to IPv6 loopback is strictly blocked."""
        result = URLSecurityValidator.validate_redirect_url(
            original_url="https://example.com/login",
            redirect_url="http://[::1]:8080/token",
        )
        assert result.is_valid is False
        assert any(k in result.rejection_reason.lower() for k in ("loopback", "blocked"))

    def test_redirect_chain_with_prohibited_destination_blocked(self) -> None:
        """Redirect target pointing to internal Class A network is blocked."""
        result = URLSecurityValidator.validate_redirect_url(
            original_url="https://example.com/step2",
            redirect_url="http://10.200.0.5/api/credentials",
        )
        assert result.is_valid is False
        assert "private" in result.rejection_reason.lower()
