# Product

## Register

product

## Users

Primary: readers of the NextHop Lab blog — recruiters, prospective clients, and fellow network engineers — arriving from a blog post to evaluate Jim's engineering credibility. They judge in the first thirty seconds: is this a real operator's tool or a toy demo? Secondary: Jim himself, using it as a genuine lab looking-glass.

## Product Purpose

RouteLens is a live network observability tool: it streams real-time BGP updates from RIPE RIS collectors worldwide, answers ad-hoc queries about any prefix/IP/ASN/hostname via multiple independent data sources (RIPEstat, RouteViews, NLNOG Ring, Globalping, Cloudflare Radar), and continuously watches the NextHop Lab's own resources. Success = a network engineer looks at it and immediately recognises operational competence; a recruiter sees a credible, alive product rather than a portfolio stub.

## Brand Personality

Precise, alive, utilitarian. A working engineer's console, not a showpiece: liveness comes from real data visibly arriving and changing — a moving ticker, climbing counters, flashing rows — never from decorative animation. Confidence expressed through density and correctness, in the manner of bgp.tools: fast, dense, no-nonsense.

## Anti-references

- The previous RouteLens look: oversized hero typography, sparse glassy cards, decorative radial glows, low information density. It read "template demo".
- Generic SaaS dashboard scaffolding: hero metrics with gradient accents, identical icon-card grids, eyebrow labels on every section.
- Sci-fi ops-centre theatrics: excessive glow, cinematic motion, dark-mode-as-costume.

## Design Principles

1. **Data is the decoration.** Every moving element must be real telemetry. If nothing is happening, show that honestly (quiet is a valid state for a stable prefix).
2. **Density earns trust.** Prefer a well-set mono table with 20 rows over a card with 3 numbers. Whitespace serves scanning, not staging.
3. **Evidence over verdicts.** Show the AS paths, the collector names, the timestamps — the raw material an engineer would check — alongside any summary badge.
4. **Instant shell, streaming panels.** Pages render immediately; independent data sources fill in as they answer, and a slow or dead source degrades to a labelled gap, never a broken page.
5. **One aesthetic register.** Dark, restrained, mono-labelled. Colour is reserved for state (healthy/warning/critical/RPKI) and the single brand accent — never mood lighting.

## Accessibility & Inclusion

Sensible defaults, not formal certification: WCAG AA contrast ratios on the dark palette (body text ≥4.5:1), `prefers-reduced-motion` fallbacks for the ticker/map pulses (crossfade or static counters), keyboard-usable search and navigation, and status conveyed by text+icon rather than colour alone.
