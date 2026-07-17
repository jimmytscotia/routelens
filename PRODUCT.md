# Product

## Register

Dark glassmorphism — restrained and premium, not decorative. Dense operational
data presented under a glass chrome: near-black cool-tinted ink, a gold signature
accent, subtle cool ambient light, Clash Display + Satoshi type with mono for
telemetry. The instrument stays dense; the framing is refined.

## Users

A technical audience — network engineers, NOC and infrastructure people, researchers, and the professionally curious — interested in investigating the live status of core parts of the Internet: global BGP activity, routing stability, RPKI posture, exchange points, and the health of specific prefixes, ASNs, and hostnames. They judge in the first thirty seconds: is this a real operator's tool or a toy demo? Secondary: the admin, using it as a genuine looking-glass.

## Product Purpose

RouteLens is a live network observability tool: it streams real-time BGP updates from RIPE RIS collectors worldwide, answers ad-hoc queries about any prefix/IP/ASN/hostname via multiple independent data sources (RIPEstat, RouteViews, NLNOG Ring, Globalping, Cloudflare Radar), watches the routing table for churn/flaps/origin changes, writes an AI "Internet Weather" briefing, and tracks the reported and routing-observed health of major services. Success = a network engineer looks at it and immediately recognises operational competence — a credible, alive instrument for inspecting the Internet's core, not a portfolio stub.

## Brand Personality

Precise, alive, and quietly premium. A working engineer's console with a refined
finish: liveness comes from real data visibly arriving and changing — a moving
ticker, climbing counters, flashing rows — not from decorative motion. The glass
and gold are the *chrome* (nav, panels, buttons, modals); the data underneath
stays dense and mono-set. Confidence expressed through density and correctness in
the manner of bgp.tools, wrapped in a cohesive, considered visual identity.

## Anti-references

- **Sparse, decorative glass**: big hero cards with three numbers, glass used to
  fill space rather than frame data. Glass belongs on the chrome, never at the
  expense of information density.
- Generic SaaS dashboard scaffolding: hero metrics with gradient accents,
  identical icon-card grids, eyebrow labels on every section.
- Sci-fi ops-centre theatrics: heavy glow, cinematic scroll-jacking, animation
  for its own sake. The ambient light is subtle; motion is reserved for real
  telemetry and light interaction feedback.

## Design Principles

1. **Data is the decoration.** Every moving element must be real telemetry. If nothing is happening, show that honestly (quiet is a valid state for a stable prefix).
2. **Density earns trust.** Prefer a well-set mono table with 20 rows over a card with 3 numbers. The glass frames the table; it does not inflate its padding.
3. **Evidence over verdicts.** Show the AS paths, the collector names, the timestamps — the raw material an engineer would check — alongside any summary badge or AI narrative.
4. **Instant shell, streaming panels.** Pages render immediately; independent data sources fill in as they answer, and a slow or dead source degrades to a labelled gap, never a broken page.
5. **Gold signs, state speaks, cool ambient light frames.** Gold is the single brand accent (logo, primary actions, active nav, highlights). Health colour (green/amber/red) is reserved for state and never competes with gold. Cool blue/cyan is for data (map, live signals, bars). The ambient gradient stays subtle — atmosphere, never the subject.

## Accessibility & Inclusion

Sensible defaults, not formal certification: WCAG AA contrast ratios on the dark palette (body text ≥4.5:1), `prefers-reduced-motion` fallbacks for the ticker/map pulses (crossfade or static counters), keyboard-usable search and navigation, and status conveyed by text+icon rather than colour alone. The glass background must never drop text below AA contrast.

## Implementation notes

- Design tokens live in `base.html` (`:root` custom properties). Re-theming is a
  token swap plus the fonts and the glass primitive.
- Fonts are self-hosted variable woff2 under `static/fonts/` (CSP-strict; no
  external font hosts).
- The ambient background is a **static CSS radial-gradient** — no WebGL shader
  (some target browsers/environments can't create a WebGL context; the same
  reason the map uses Leaflet, not MapLibre).
