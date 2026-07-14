# RouteLens backend design

## Feasibility recommendation

Start with Flask + stdlib `sqlite3` for the MVP. RouteLens stores time-series snapshots and JSON details, but the query needs are simple: resources, latest check per resource/check type, and historical rows by time. Stdlib SQLite avoids a SQLAlchemy dependency while remaining easy to migrate later. If the app grows to multi-user writes, background workers, or complex filtering over JSON fields, add SQLAlchemy models over the same tables.

## Core schema

### `resources`

Represents monitored hostnames, URLs, and public BGP prefixes.

```sql
CREATE TABLE resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  resource_type TEXT NOT NULL CHECK (resource_type IN ('hostname','prefix','url')),
  expected_mode TEXT NOT NULL DEFAULT 'public'
    CHECK (expected_mode IN ('public','private_lab','bgp_public','internal_only')),
  expected_ips TEXT NOT NULL DEFAULT '[]',          -- JSON array
  expected_origin_asn INTEGER,
  expected_url TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Seed resources:

| name | type | expected |
|---|---|---|
| `nexthop.engineer` | hostname | public A/AAAA includes `66.241.124.199`, HTTPS healthy |
| `web.nexthop.engineer` | hostname | private/lab DNS to `100.94.135.62`, no public DNS leak |
| `grafana.nexthop.engineer` | hostname | private/lab DNS to `100.94.135.62`, no public DNS leak |
| `prometheus.nexthop.engineer` | hostname | private/lab DNS to `100.94.135.62`, no public DNS leak |
| `8.8.8.0/24` | prefix | public BGP, expected origin AS15169 |
| `1.1.1.0/24` | prefix | public BGP, expected origin AS13335 |

### `check_results`

Append-only observations from DNS, TLS, HTTP, RIPEstat/BGP, and insight passes.

```sql
CREATE TABLE check_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  resource_id INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
  check_type TEXT NOT NULL CHECK (check_type IN ('dns','tls','http','bgp','insight')),
  status TEXT NOT NULL CHECK (status IN ('healthy','warning','critical','unknown')),
  summary TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',         -- serialized checker-specific details
  checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_check_results_resource_type_time
  ON check_results(resource_id, check_type, checked_at DESC, id DESC);
```

Recommended `details_json` payloads:

- DNS: `public_resolvers`, `private_resolvers`, `public_ips`, `private_ips`, `rcode_by_resolver`, `duration_ms`, `errors`.
- TLS: `subject`, `issuer`, `not_before`, `not_after`, `days_remaining`, `san_dns`, `matched_hostname`, `chain_ok`, `error`.
- HTTP: `url`, `method`, `status_code`, `duration_ms`, `ok`, `redirect_chain`, `content_type`, `body_sha256_prefix`, `error`.
- BGP: RIPEstat `resource`, `collector_count`, `unique_path_count`, `origins`, `origin_counts`, `top_transit_asns`, `sample_paths`, `rpki_status`, `errors`.
- Insight: normalized findings that explain what a network engineer should do next.

Optional future tables: `resolver_profiles` for named public/private DNS servers, `incidents` for deduplicated alert state, and `jobs` for scheduler audit.

## Checker and ingestion interfaces

```python
@dataclass(frozen=True)
class CheckResult:
    resource_name: str
    check_type: Literal['dns','tls','http','bgp','insight']
    status: Literal['healthy','warning','critical','unknown']
    summary: str
    details: dict[str, Any]
    checked_at: datetime

class Checker(Protocol):
    check_type: str
    def run(self, resource: dict[str, Any]) -> CheckResult: ...

class IngestionSink(Protocol):
    def record_check(self, *, resource_id: int, check_type: str,
                     status: str, summary: str,
                     details: dict[str, Any] | None = None) -> int: ...
```

Planned concrete checkers:

1. `DNSChecker(public_resolvers, private_resolvers)`: compare public resolvers such as `1.1.1.1`/`8.8.8.8` against private/lab resolvers. For `private_lab`, public A/AAAA answers are critical leaks; private answers matching expected IPs are healthy.
2. `TLSChecker(timeout)`: connect with SNI, verify certificate chain and hostname, compute expiry. Warn under 30 days, critical when expired/hostname mismatch/chain invalid.
3. `HTTPChecker(timeout, expected_statuses={200,204,301,302})`: GET/HEAD expected URL, measure latency, capture status and redirect chain. Critical on connection failure or bad status; warning on slow responses.
4. `RIPEstatBGPChecker(timeout)`: call `https://stat.ripe.net/data/bgplay/data.json?resource=<prefix>`, summarize collectors, unique AS paths, origins and transits. Pair with RPKI endpoint later.
5. `InsightEngine`: consumes latest DNS/TLS/HTTP/BGP rows and writes an `insight` row with actionable findings.

Ingestion flow:

1. Load enabled resources.
2. Select checkers by `resource_type` and `expected_mode`.
3. Run checks with hard per-check timeouts.
4. Persist every result, including failures as `unknown`/`critical` with `error` details.
5. Run insight classification after raw check rows are stored.

## TDD test plan

### Store and Flask app

- Schema initialization creates `resources` and `check_results` idempotently.
- Default seed includes the NextHop public site, private lab services, and BGP examples.
- Upsert preserves a stable resource id and updates expected metadata.
- Recording a check serializes JSON details and latest-check lookup returns most recent row per check type.
- Foreign-key cascade deletes old checks when a resource is removed.
- `/healthz` returns JSON `{"status":"ok"}`.
- Dashboard renders seeded resources and latest statuses.

### RIPEstat/BGP

- `summarize_bgplay` extracts collector count, unique paths, origin ASNs, origin counts, top transit ASNs, and sample paths.
- Empty `initial_state` returns zero collectors/paths and no origins, then insight marks critical no visibility.
- Multiple origins for one prefix are warning/critical unless expected origin is included and policy allows MOAS.
- Origin mismatch is critical, e.g. expected AS15169 but observed AS64500.
- RIPEstat timeout/HTTP error persists an `unknown` BGP check with error details instead of crashing ingestion.
- RPKI invalid overrides otherwise healthy visibility to critical.

### DNS public/private

- Public hostname is healthy when public answer equals expected `66.241.124.199`.
- Public hostname is critical when public resolvers return NXDOMAIN/no answer.
- Public hostname is warning when it resolves, but not to expected IPs.
- Private lab host is healthy when public DNS is absent and private DNS returns `100.94.135.62`.
- Private lab host is critical when public resolvers return private/lab address or any public answer.
- Split-horizon mismatch: private resolver returns an unexpected IP -> warning/critical based on policy.
- Resolver partial failure: one public resolver times out but others agree -> warning with resolver error details.
- IPv6-only/dual-stack answers are normalized and compared as sets.

### TLS

- Valid certificate matching hostname and expiring after threshold is healthy.
- Certificate under 30 days is warning; expired is critical.
- SAN/CN hostname mismatch is critical.
- Self-signed/untrusted chain is critical for public services; warning or configurable for private lab.
- SNI failure, TCP timeout, and non-TLS endpoint produce critical with error details.
- Clock/parse edge cases: missing `notAfter`, timezone offsets, wildcard SAN matching.

### HTTP health

- Expected 2xx/3xx status within latency budget is healthy.
- 4xx/5xx, connection refused, TLS handshake failure, and timeout are critical.
- Slow but successful response is warning.
- Redirect loop or too many redirects is critical.
- Private lab services may be expected to fail from outside the lab; classify according to resolver/source profile.

### Insights

- DNS leak for `grafana.nexthop.engineer` or `prometheus.nexthop.engineer` is critical and actionable.
- Public site DNS, TLS, and HTTP all healthy produces an `info`/healthy insight.
- Prefix with no collector visibility or no origin is critical.
- Prefix with low collector count is warning.
- RPKI invalid is critical even if origin matches.
- Correlate DNS OK + HTTP failure as likely service/listener issue; DNS failure + HTTP skipped as name-resolution issue.

## Edge cases to keep explicit

- Lab/private DNS should not be considered broken merely because public DNS returns no answer.
- Public DNS returning RFC1918/CGNAT/Tailscale addresses should be treated as a leak for public resolvers.
- JSON details must remain serializable; store raw exceptions as strings, not exception objects.
- Every network checker must have a timeout and record failures as rows.
- Latest-check queries should use monotonically increasing `id` as a tie-breaker when timestamps match.
- Use fixtures/mocks for RIPEstat, DNS, TLS, and HTTP; no unit test should require live Internet.
