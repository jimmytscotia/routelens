from __future__ import annotations

import ipaddress
import re
from typing import Any

# RFC 1123 hostname: dot-separated labels of letters/digits/hyphens,
# no leading/trailing hyphen, at least one dot so bare words are rejected.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"
)
_ASN_RE = re.compile(r"^(?:as)?([0-9]{1,10})$", re.IGNORECASE)


def classify_query(raw: str) -> dict[str, Any]:
    """Classify free-form search input as a prefix, IP, ASN, or hostname.

    Bare integers are treated as ASNs. Prefixes with host bits set are
    normalised to their network address so downstream APIs get a clean key.
    """
    text = (raw or "").strip()
    if not text:
        return {"kind": "invalid", "value": None}

    if "/" in text:
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError:
            return {"kind": "invalid", "value": None}
        return {"kind": "prefix", "value": str(network)}

    try:
        return {"kind": "ip", "value": str(ipaddress.ip_address(text))}
    except ValueError:
        pass

    asn = _ASN_RE.match(text)
    if asn:
        number = int(asn.group(1))
        if 0 < number <= 4_294_967_295:
            return {"kind": "asn", "value": number}
        return {"kind": "invalid", "value": None}

    hostname = text.lower().rstrip(".")
    # RFC 3696: the top-level label cannot be all-numeric, which also stops
    # malformed IPs like 999.1.1.1 classifying as hostnames.
    if _HOSTNAME_RE.match(hostname) and not hostname.rsplit(".", 1)[-1].isdigit():
        return {"kind": "hostname", "value": hostname}

    return {"kind": "invalid", "value": None}
