from __future__ import annotations

import datetime as dt
import socket
import ssl
from urllib.parse import urlparse
import urllib.request

import dns.resolver

from .insights import classify_dns_visibility


def resolve_a(server: str, hostname: str, timeout: float = 3.0) -> list[str]:
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [server]
    resolver.timeout = timeout
    resolver.lifetime = timeout
    try:
        answers = resolver.resolve(hostname, "A")
    except Exception:
        return []
    return sorted({a.to_text() for a in answers})


def dns_check(
    hostname: str,
    expected_mode: str,
    public_resolver: str = "1.1.1.1",
    private_resolver: str = "100.88.168.126",
    expected_ips: list[str] | None = None,
    resolver=resolve_a,
) -> dict:
    public_ips = resolver(public_resolver, hostname)
    private_ips = resolver(private_resolver, hostname)
    insight = classify_dns_visibility(hostname, expected_mode, public_ips, private_ips, expected_ips)
    return {
        "check_type": "dns",
        "status": insight["status"],
        "summary": insight["summary"],
        "details": {
            "hostname": hostname,
            "expected_mode": expected_mode,
            "public_resolver": public_resolver,
            "private_resolver": private_resolver,
            "public_ips": public_ips,
            "private_ips": private_ips,
            "expected_ips": expected_ips or [],
        },
    }


def http_check_from_response(url: str, status_code: int | None, bytes_read: int, error: str | None) -> dict:
    if error:
        return {"check_type": "http", "status": "critical", "summary": f"{url} failed: {error}", "details": {"url": url, "error": error}}
    if status_code and 200 <= status_code < 400:
        return {"check_type": "http", "status": "healthy", "summary": f"{url} returned HTTP {status_code}", "details": {"url": url, "status_code": status_code, "bytes": bytes_read}}
    return {"check_type": "http", "status": "warning", "summary": f"{url} returned HTTP {status_code}", "details": {"url": url, "status_code": status_code, "bytes": bytes_read}}


def http_check(url: str, timeout: float = 8.0, connect_host: str | None = None) -> dict:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        if connect_host:
            context = ssl.create_default_context()
            port = parsed.port or 443
            with socket.create_connection((connect_host, port), timeout=timeout) as raw_sock:
                with context.wrap_socket(raw_sock, server_hostname=hostname) as tls_sock:
                    request = (
                        f"GET {path} HTTP/1.1\r\n"
                        f"Host: {hostname}\r\n"
                        "User-Agent: RouteLens/0.1\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode()
                    tls_sock.sendall(request)
                    data = b""
                    while len(data) < 8192:
                        chunk = tls_sock.recv(4096)
                        if not chunk:
                            break
                        data += chunk
            status_line = data.split(b"\r\n", 1)[0].decode("latin1", "replace")
            parts = status_line.split()
            status_code = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
            return http_check_from_response(url, status_code, len(data), None)
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "RouteLens/0.1"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4096)
            return http_check_from_response(url, response.status, len(body), None)
    except Exception as exc:
        return http_check_from_response(url, None, 0, str(exc))


def tls_expiry_status(days_remaining: int, issuer: str, sans: list[str]) -> dict:
    if days_remaining < 0:
        status = "critical"
        summary = f"TLS certificate expired {-days_remaining} days ago"
    elif days_remaining < 7:
        status = "critical"
        summary = f"TLS certificate expires in {days_remaining} days"
    elif days_remaining < 30:
        status = "warning"
        summary = f"TLS certificate expires in {days_remaining} days"
    else:
        status = "healthy"
        summary = f"TLS certificate valid for {days_remaining} days"
    return {
        "check_type": "tls",
        "status": status,
        "summary": summary,
        "details": {"days_remaining": days_remaining, "issuer": issuer, "sans": sans},
    }


def tls_check(hostname: str, port: int = 443, timeout: float = 5.0, connect_host: str | None = None) -> dict:
    try:
        context = ssl.create_default_context()
        target = connect_host or hostname
        with socket.create_connection((target, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
        not_after = cert.get("notAfter")
        expiry = dt.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
        days = int((expiry - dt.datetime.now(dt.timezone.utc)).total_seconds() // 86400)
        issuer = ", ".join("=".join(part) for rdn in cert.get("issuer", []) for part in rdn)
        sans = [value for kind, value in cert.get("subjectAltName", []) if kind == "DNS"]
        return tls_expiry_status(days, issuer, sans)
    except Exception as exc:
        return {"check_type": "tls", "status": "critical", "summary": f"TLS check failed for {hostname}: {exc}", "details": {"hostname": hostname, "error": str(exc)}}
