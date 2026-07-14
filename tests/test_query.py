import pytest

from routelens.query import classify_query


@pytest.mark.parametrize(
    ("raw", "kind", "value"),
    [
        ("8.8.8.0/24", "prefix", "8.8.8.0/24"),
        ("2001:db8::/32", "prefix", "2001:db8::/32"),
        ("8.8.8.8", "ip", "8.8.8.8"),
        ("2606:4700:4700::1111", "ip", "2606:4700:4700::1111"),
        ("AS15169", "asn", 15169),
        ("as13335", "asn", 13335),
        ("15169", "asn", 15169),
        ("nexthop.engineer", "hostname", "nexthop.engineer"),
        ("Grafana.NextHop.Engineer", "hostname", "grafana.nexthop.engineer"),
        ("  8.8.8.0/24  ", "prefix", "8.8.8.0/24"),
    ],
)
def test_classify_query_detects_kind_and_normalises(raw, kind, value):
    result = classify_query(raw)

    assert result["kind"] == kind
    assert result["value"] == value


def test_classify_query_normalises_host_prefix_to_network():
    # A prefix written with host bits set is normalised to the network address.
    result = classify_query("8.8.8.13/24")

    assert result["kind"] == "prefix"
    assert result["value"] == "8.8.8.0/24"


@pytest.mark.parametrize("raw", ["", "   ", "999.1.1.1", "not a query!", "AS", "as-1", "http://", "a..b"])
def test_classify_query_rejects_invalid_input(raw):
    result = classify_query(raw)

    assert result["kind"] == "invalid"
