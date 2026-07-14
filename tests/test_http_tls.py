from routelens.checks import http_check_from_response, tls_expiry_status, http_check, tls_check


def test_http_check_from_response_classifies_2xx_as_healthy():
    result = http_check_from_response("https://web.nexthop.engineer/", 200, 982, error=None)

    assert result["status"] == "healthy"
    assert "HTTP 200" in result["summary"]


def test_http_check_from_response_classifies_error_as_critical():
    result = http_check_from_response("https://web.nexthop.engineer/", None, 0, error="timeout")

    assert result["status"] == "critical"
    assert "timeout" in result["summary"]


def test_tls_expiry_status_warns_inside_30_days():
    result = tls_expiry_status(days_remaining=12, issuer="Lets Encrypt", sans=["web.nexthop.engineer"])

    assert result["status"] == "warning"
    assert "12 days" in result["summary"]


def test_tls_expiry_status_healthy_with_long_validity():
    result = tls_expiry_status(days_remaining=88, issuer="Lets Encrypt", sans=["web.nexthop.engineer"])

    assert result["status"] == "healthy"
    assert result["details"]["issuer"] == "Lets Encrypt"
