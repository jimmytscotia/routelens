"""Nothing in the code should assume one particular operator's estate.

A fresh clone of this repo must not carry someone else's split-horizon
resolver, health-check URLs or contact details. Each is configuration, and
each degrades sensibly when it is absent.
"""

import routelens.sources as sources
from routelens.checks import dns_check
from routelens.collector import http_url_for_resource


def test_private_resolver_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("ROUTELENS_PRIVATE_RESOLVER", "192.0.2.53")
    seen = []

    def resolver(server, hostname):
        seen.append(server)
        return []

    dns_check(hostname="host.example", expected_mode="public", resolver=resolver)

    assert "192.0.2.53" in seen


def test_private_resolution_is_skipped_when_no_resolver_is_configured(monkeypatch):
    monkeypatch.delenv("ROUTELENS_PRIVATE_RESOLVER", raising=False)
    seen = []

    def resolver(server, hostname):
        seen.append(server)
        return ["192.0.2.10"]

    result = dns_check(hostname="host.example", expected_mode="public", resolver=resolver)

    # Only the public resolver is consulted, and the check still completes.
    assert seen == ["1.1.1.1"]
    assert result["details"]["private_ips"] == []
    assert result["details"]["private_resolver"] is None


def test_http_url_prefers_the_resources_own_url():
    resource = {"name": "host.example", "expected_url": "https://host.example/-/ready"}

    assert http_url_for_resource(resource) == "https://host.example/-/ready"


def test_http_url_falls_back_to_the_hostname():
    assert http_url_for_resource({"name": "host.example"}) == "https://host.example/"


def test_user_agent_is_configurable_and_neutral_by_default(monkeypatch):
    monkeypatch.delenv("ROUTELENS_USER_AGENT", raising=False)

    assert "nexthop" not in sources.build_user_agent()
    assert "RouteLens" in sources.build_user_agent()

    monkeypatch.setenv("ROUTELENS_USER_AGENT", "RouteLens/1.0 (https://x.example; noc@x.example)")

    assert sources.build_user_agent() == "RouteLens/1.0 (https://x.example; noc@x.example)"
