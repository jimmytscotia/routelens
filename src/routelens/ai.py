"""Mistral client for the Internet Weather briefing.

Reads MISTRAL_API_KEY from the environment (never the repo); `from_env`
returns None when unset so the app degrades to "generator not configured"
rather than erroring. The SDK client is injectable for testing.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

# Mistral Small 4 — cheapest model with strong instruction-following and
# schema-enforced JSON; EU-resident processing. ~$0.25/month at 6-hourly.
MODEL = "mistral-small-latest"

WEATHER_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "internet_weather",
        "strict": True,
        # The 2.x mistralai SDK names this key `schema_definition`, not `schema`
        # (the raw REST field). A mismatch is silently ignored, disabling
        # structured output — see test_weather_schema_matches_installed_sdk.
        "schema_definition": {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "severity": {"type": "string", "enum": ["calm", "minor", "notable", "severe"]},
                "body_md": {"type": "string"},
            },
            "required": ["headline", "severity", "body_md"],
            "additionalProperties": False,
        },
    },
}

SYSTEM_PROMPT = """You are the forecaster for RouteLens "Internet Weather", \
briefing a technical audience (network engineers, NOC staff) on the live state \
of the global Internet's core routing over the last six hours.

You are given JSON evidence with two parts: `internal` — RouteLens's own \
observations from the RIPE RIS BGP firehose (collector activity spikes, \
country churn hotspots, top churning ASNs, flapping prefixes, confirmed \
origin changes) — and external outage/hijack feeds: `ioda` (Georgia Tech \
outage alerts per country/ASN), `grip` (BGP hijack-candidate events with a \
suspicion score), and `radar_outages` (Cloudflare Radar outage annotations \
with causes).

Write a briefing that:
- Leads with a one-line headline capturing the single most important thing.
- Sets severity honestly: `calm` when nothing notable is happening (this is \
common and fine — say so plainly, do not manufacture drama), `minor` for \
isolated regional events, `notable` for widespread or multiple concurrent \
events, `severe` only for major global disruption.
- Structures `body_md` (markdown, ~150-300 words) for fast scanning, NOT as \
one dense block: open with a single-sentence lead capturing the overall \
picture; then one or two short paragraphs; then, when there is anything worth \
monitoring, a `## Watch` section as a bullet list of specific ASNs/prefixes \
with a few words each. The valuable part is drawing explicit correlations \
between the internal BGP signals and the external outage/hijack feeds when \
they line up (e.g. an IODA outage in a country whose origins also spiked in \
our churn data, or a GRIP hijack candidate matching a confirmed origin change).

Ground every statement in the evidence. Never invent events, numbers, \
countries, or ASNs not present in the data. Refer to ASNs by their number \
(e.g. `AS15169`) and use ONLY the operator names and country labels that \
appear in the evidence — do not add your own enrichment (no guessed company \
names, cities, or countries). If a feed is empty, simply don't mention it. \
Attribute external data briefly (IODA, GRIP, Cloudflare Radar) where you \
rely on it."""


def _import_mistral():
    """The Mistral client class. SDK 2.x moved it to `mistralai.client`;
    1.x exposed it at the top level. Try 2.x first, fall back."""
    try:
        from mistralai.client import Mistral  # SDK 2.x
    except ImportError:  # pragma: no cover - 1.x fallback
        from mistralai import Mistral
    return Mistral


EXPLAIN_SYSTEM = """You are a network engineer explaining a single BGP event \
to a technical but time-pressed reader, in 2-3 plain sentences. Say what the \
event means, whether it looks routine (maintenance, traffic engineering, \
normal multihoming) or worth investigating (possible leak, hijack, or \
instability), and what a reader could check next (e.g. RPKI validity, the \
prefix in the looking glass). Ground everything in the values given; never \
invent ASNs, prefixes, or facts not present. No preamble, no markdown headers \
— just the explanation."""


class WeatherAI:
    def __init__(self, client: Any, model: str = MODEL):
        self._client = client
        self.model = model

    @classmethod
    def from_env(cls) -> "WeatherAI | None":
        key = os.environ.get("MISTRAL_API_KEY")
        if not key:
            return None
        return cls(_import_mistral()(api_key=key))

    def explain(self, context: str) -> str:
        """A short plain-English explanation of a single BGP event."""
        response = self._client.chat.complete(
            model=self.model,
            messages=[
                {"role": "system", "content": EXPLAIN_SYSTEM},
                {"role": "user", "content": context},
            ],
            temperature=0.2,
        )
        return (response.choices[0].message.content or "").strip()

    def summarize(self, evidence: dict[str, Any]) -> dict[str, Any]:
        response = self._client.chat.complete(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Evidence:\n" + json.dumps(evidence, default=str)},
            ],
            response_format=WEATHER_SCHEMA,
            temperature=0.3,
        )
        content = response.choices[0].message.content
        return _parse_json(content)


def _parse_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise
