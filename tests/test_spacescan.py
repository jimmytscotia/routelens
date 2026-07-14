from routelens.spacescan import accumulate_table_lines, merged_length, scan_to_store
from routelens.store import RouteLensStore


def test_merged_length_unions_overlapping_ranges():
    # /9 covering a /24 inside it: union is just the /9.
    ranges = [(0, 2**23 - 1), (1000, 1255)]
    assert merged_length(sorted(ranges)) == 2**23
    # Disjoint ranges sum.
    assert merged_length([(0, 255), (512, 767)]) == 512
    assert merged_length([]) == 0


def test_accumulate_groups_ranges_per_asn_and_family():
    lines = [
        '{"CIDR":"8.0.0.0/9","ASN":3356,"Hits":100}',
        '{"CIDR":"8.8.8.0/24","ASN":15169,"Hits":900}',
        '{"CIDR":"2001:4860::/32","ASN":15169,"Hits":500}',
        'not json',
        '{"CIDR":"bad//","ASN":1}',
    ]

    v4, v6, counts = accumulate_table_lines(lines)

    assert len(v4[3356]) == 1
    assert v4[3356][0][1] - v4[3356][0][0] + 1 == 2**23
    assert len(v4[15169]) == 1
    assert len(v6[15169]) == 1
    assert counts[15169] == 2
    assert counts[3356] == 1


def test_scan_to_store_dedupes_same_asn_overlap(tmp_path):
    store = RouteLensStore(tmp_path / "space.db")
    store.init_schema()
    store.upsert_asn_names([(3356, "Lumen", "US")])
    lines = [
        # Lumen announces an aggregate /9 and a more-specific /24 inside it:
        # the /24 must not add to its total.
        '{"CIDR":"8.0.0.0/9","ASN":3356,"Hits":1}',
        '{"CIDR":"8.7.7.0/24","ASN":3356,"Hits":1}',
        # A different AS announcing a more-specific inside Lumen space is
        # credited separately (announced-space semantics).
        '{"CIDR":"8.8.8.0/24","ASN":15169,"Hits":1}',
        '{"CIDR":"2001:4860::/32","ASN":15169,"Hits":1}',
    ]

    written = scan_to_store(store, lines)

    assert written == 2
    rows = {r["asn"]: r for r in store.address_space_league(limit=10)}
    # /9 = 2^15 /24-equivalents, unchanged by its inner /24.
    assert rows[3356]["v4_slash24"] == 2**15
    assert rows[3356]["prefixes"] == 2
    assert rows[15169]["v4_slash24"] == 1
    # /32 = 2^16 /48-equivalents.
    assert rows[15169]["v6_slash48"] == 2**16
    assert rows[3356]["name"] == "Lumen"
    # League ranks by v4 space.
    league = store.address_space_league(limit=10)
    assert league[0]["asn"] == 3356


def test_rescan_replaces_previous_totals(tmp_path):
    store = RouteLensStore(tmp_path / "space.db")
    store.init_schema()
    scan_to_store(store, ['{"CIDR":"8.0.0.0/9","ASN":3356,"Hits":1}'])
    scan_to_store(store, ['{"CIDR":"9.9.9.0/24","ASN":64500,"Hits":1}'])

    rows = store.address_space_league(limit=10)

    # Old scan's ASNs are gone: the table reflects the latest scan only.
    assert [r["asn"] for r in rows] == [64500]
