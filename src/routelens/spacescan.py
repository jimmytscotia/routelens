"""Address-space scanner: who announces how much of the Internet.

Ingests the bgp.tools daily table dump (~1.5M prefix->origin rows, 71MB)
and writes per-ASN announced-space totals. Runs as a oneshot process on a
daily systemd timer — deliberately NOT inside the streaming aggregator,
whose memory budget must stay small to keep up with RIS Live.

    ROUTELENS_DATABASE=/var/lib/routelens/routelens.db python -m routelens.spacescan

Accounting: within one ASN, overlapping announcements are merged (an
aggregate plus its own more-specifics counts once). Across ASNs, overlaps
are both credited — this measures announced space, and two networks can
genuinely announce overlapping blocks.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
from typing import Iterable

import requests

from .sources import USER_AGENT
from .store import RouteLensStore

log = logging.getLogger("routelens.spacescan")

TABLE_URL = "https://bgp.tools/table.jsonl"


def accumulate_table_lines(lines: Iterable[str]):
    """Group announced ranges per ASN per family. Returns (v4, v6, counts)
    where v4/v6 map asn -> list of (first_addr, last_addr) ints."""
    v4: dict[int, list] = {}
    v6: dict[int, list] = {}
    counts: dict[int, int] = {}
    for line in lines:
        try:
            row = json.loads(line)
            asn = int(row["ASN"])
            network = ipaddress.ip_network(row["CIDR"], strict=False)
        except (ValueError, KeyError, TypeError):
            continue
        first = int(network.network_address)
        last = int(network.broadcast_address)
        target = v4 if network.version == 4 else v6
        target.setdefault(asn, []).append((first, last))
        counts[asn] = counts.get(asn, 0) + 1
    return v4, v6, counts


def merged_length(sorted_ranges: list[tuple[int, int]]) -> int:
    """Total addresses covered by the union of sorted (first, last) ranges."""
    total = 0
    covered_until = -1
    for first, last in sorted_ranges:
        if last <= covered_until:
            continue
        total += last - max(first, covered_until + 1) + 1
        covered_until = last
    return total


def scan_to_store(store: RouteLensStore, lines: Iterable[str]) -> int:
    v4, v6, counts = accumulate_table_lines(lines)
    rows = []
    for asn in counts:
        v4_addrs = merged_length(sorted(v4.get(asn, [])))
        v6_addrs = merged_length(sorted(v6.get(asn, [])))
        rows.append(
            {
                "asn": asn,
                "v4_slash24": v4_addrs // 256,
                "v6_slash48": v6_addrs >> 80,  # 2^(128-48) addresses per /48
                "prefixes": counts[asn],
            }
        )
    store.replace_address_space(rows)
    return len(rows)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = os.environ.get("ROUTELENS_DATABASE", "/var/lib/routelens/routelens.db")
    store = RouteLensStore(db)
    store.init_schema()
    log.info("fetching %s", TABLE_URL)
    response = requests.get(TABLE_URL, headers={"User-Agent": USER_AGENT}, timeout=300, stream=True)
    response.raise_for_status()
    written = scan_to_store(store, response.iter_lines(decode_unicode=True))
    log.info("scanned announced space for %d ASNs into %s", written, db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
