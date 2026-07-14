from routelens.collector import checks_for_resource


def test_checks_for_private_hostname_includes_dns_http_tls():
    resource = {"name": "web.nexthop.engineer", "resource_type": "hostname", "expected_mode": "private_lab", "expected_public_ip": None}

    checks = checks_for_resource(resource)

    assert checks == ["dns", "http", "tls"]


def test_checks_for_prefix_includes_bgp_only():
    resource = {"name": "8.8.8.0/24", "resource_type": "prefix", "expected_mode": "bgp_watch"}

    checks = checks_for_resource(resource)

    assert checks == ["bgp"]
