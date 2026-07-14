from __future__ import annotations


def _same_set(left, right):
    return set(left or []) == set(right or [])


def classify_dns_visibility(
    hostname: str,
    expected_mode: str,
    public_ips: list[str],
    private_ips: list[str],
    expected_ips: list[str] | None = None,
) -> dict:
    public_ips = public_ips or []
    private_ips = private_ips or []
    expected_ips = expected_ips or []

    if expected_mode == "private_lab":
        if public_ips:
            return {
                "status": "critical",
                "severity": "critical",
                "summary": f"{hostname} has a public DNS leak: {', '.join(public_ips)}",
            }
        if private_ips:
            return {
                "status": "healthy",
                "severity": "info",
                "summary": f"{hostname} private DNS is present and public DNS is intentionally absent",
            }
        return {"status": "critical", "severity": "critical", "summary": f"{hostname} has no private DNS answer"}

    if expected_mode == "public":
        if expected_ips and _same_set(public_ips, expected_ips) and (not private_ips or _same_set(private_ips, expected_ips)):
            return {
                "status": "healthy",
                "severity": "info",
                "summary": f"{hostname} matches expected public address {', '.join(expected_ips)}",
            }
        if not public_ips:
            return {"status": "critical", "severity": "critical", "summary": f"{hostname} has no public DNS answer"}
        return {"status": "warning", "severity": "warning", "summary": f"{hostname} resolves publicly to {', '.join(public_ips)}"}

    return {"status": "unknown", "severity": "warning", "summary": f"{hostname} has unknown expected mode {expected_mode}"}


def score_prefix_health(
    prefix: str,
    expected_origin: int | None,
    observed_origins: list[int],
    collector_count: int,
    unique_path_count: int,
    rpki_status: str = "unknown",
) -> dict:
    findings: list[str] = []
    status = "healthy"
    severity = "info"

    if expected_origin is not None and observed_origins and expected_origin not in observed_origins:
        findings.append(f"Origin mismatch: expected AS{expected_origin}, observed {', '.join('AS'+str(x) for x in observed_origins)}")
        status = "critical"
        severity = "critical"
    if not observed_origins:
        findings.append("No observed origin ASN")
        status = "critical"
        severity = "critical"
    if collector_count == 0:
        findings.append("No collector visibility")
        status = "critical"
        severity = "critical"
    elif collector_count < 5 and status != "critical":
        findings.append("Low collector visibility")
        status = "warning"
        severity = "warning"
    if rpki_status.lower() == "invalid":
        findings.append("RPKI invalid")
        status = "critical"
        severity = "critical"
    if not findings:
        findings.append("Prefix visibility and origin look normal")

    return {
        "prefix": prefix,
        "status": status,
        "severity": severity,
        "findings": findings,
        "collector_count": collector_count,
        "unique_path_count": unique_path_count,
        "observed_origins": observed_origins,
        "rpki_status": rpki_status,
    }
