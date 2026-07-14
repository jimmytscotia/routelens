from routelens.checks import dns_check


def test_dns_check_compares_public_and_private_answers_with_injected_resolvers():
    def resolver(server, hostname):
        if server == "public":
            return []
        if server == "private":
            return ["100.94.135.62"]
        raise AssertionError(server)

    result = dns_check(
        hostname="web.nexthop.engineer",
        expected_mode="private_lab",
        public_resolver="public",
        private_resolver="private",
        resolver=resolver,
    )

    assert result["status"] == "healthy"
    assert result["details"]["public_ips"] == []
    assert result["details"]["private_ips"] == ["100.94.135.62"]
