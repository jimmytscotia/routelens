from __future__ import annotations

from .checks import dns_check, http_check, tls_check
from .insights import score_prefix_health
from .ripestat import fetch_bgplay, summarize_bgplay
from .store import RouteLensStore


def checks_for_resource(resource: dict) -> list[str]:
    if resource["resource_type"] == "prefix":
        return ["bgp"]
    return ["dns", "http", "tls"]


def url_for_hostname(hostname: str) -> str:
    return f"https://{hostname}/"


def run_resource_checks(store: RouteLensStore, resource: dict) -> list[dict]:
    results = []
    expected_ips = resource.get("expected_ips") or []
    connect_host = expected_ips[0] if resource.get("expected_mode") == "private_lab" and expected_ips else None
    for check in checks_for_resource(resource):
        if check == "dns":
            result = dns_check(resource["name"], resource["expected_mode"], expected_ips=expected_ips)
        elif check == "http":
            url = resource.get("expected_url") or url_for_hostname(resource["name"])
            if resource["name"] == "prometheus.nexthop.engineer":
                url = "https://prometheus.nexthop.engineer/-/ready"
            elif resource["name"] == "grafana.nexthop.engineer":
                url = "https://grafana.nexthop.engineer/api/health"
            elif resource["name"] == "web.nexthop.engineer":
                url = "https://web.nexthop.engineer/healthz"
            result = http_check(url, connect_host=connect_host)
        elif check == "tls":
            result = tls_check(resource["name"], connect_host=connect_host)
        elif check == "bgp":
            try:
                summary = summarize_bgplay(fetch_bgplay(resource["name"]))
                health = score_prefix_health(
                    prefix=resource["name"],
                    expected_origin=None,
                    observed_origins=summary["origins"],
                    collector_count=summary["collector_count"],
                    unique_path_count=summary["unique_path_count"],
                )
                result = {
                    "check_type": "bgp",
                    "status": health["status"],
                    "summary": "; ".join(health["findings"]),
                    "details": summary,
                }
            except Exception as exc:
                result = {"check_type": "bgp", "status": "critical", "summary": f"BGP fetch failed: {exc}", "details": {"error": str(exc)}}
        else:
            continue
        store.record_check(
            resource_id=resource["id"],
            check_type=result["check_type"],
            status=result["status"],
            summary=result["summary"],
            details=result["details"],
        )
        results.append(result)
    return results


def run_all_checks(store: RouteLensStore) -> list[dict]:
    store.init_schema()
    store.seed_defaults()
    all_results = []
    for resource in store.list_resources():
        for result in run_resource_checks(store, resource):
            all_results.append({"resource": resource["name"], **result})
    return all_results
