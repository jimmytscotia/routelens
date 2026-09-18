from routelens.insights import classify_dns_visibility, score_prefix_health


def test_lab_only_service_is_healthy_when_public_dns_absent_and_private_dns_present():
    result = classify_dns_visibility(
        hostname="web.internal.example",
        expected_mode="private_lab",
        public_ips=[],
        private_ips=["192.0.2.20"],
    )

    assert result["status"] == "healthy"
    assert result["severity"] == "info"
    assert "public DNS is intentionally absent" in result["summary"]


def test_lab_only_service_is_critical_when_public_dns_leaks_private_service():
    result = classify_dns_visibility(
        hostname="grafana.internal.example",
        expected_mode="private_lab",
        public_ips=["192.0.2.20"],
        private_ips=["192.0.2.20"],
    )

    assert result["status"] == "critical"
    assert result["severity"] == "critical"
    assert "public DNS leak" in result["summary"]


def test_public_site_is_healthy_when_public_and_private_dns_match_expected_public_ip():
    result = classify_dns_visibility(
        hostname="example.com",
        expected_mode="public",
        public_ips=["198.51.100.10"],
        private_ips=["198.51.100.10"],
        expected_ips=["198.51.100.10"],
    )

    assert result["status"] == "healthy"
    assert result["severity"] == "info"
    assert "matches expected public address" in result["summary"]


def test_prefix_health_warns_on_origin_mismatch():
    result = score_prefix_health(
        prefix="203.0.113.0/24",
        expected_origin=64500,
        observed_origins=[64501],
        collector_count=100,
        unique_path_count=12,
        rpki_status="unknown",
    )

    assert result["status"] == "critical"
    assert any("origin mismatch" in item.lower() for item in result["findings"])
