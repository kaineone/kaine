# Design — `local-womb-feed`

The womb's design is the archived `gestational-womb-stimulus/design.md`
(`openspec/changes/archive/2026-07-10-gestational-womb-stimulus/`), adopted as written:
the feed architecture (§3), the two coupled rhythms (§4), the external maternal
state (§5), welfare during gestation (§5a), the self-rhythm drive seam (§6), the
sense-onset and colour schedule (§7), the readiness readout (§8), reproducibility and
zero persistence (§9), the emergent-not-hardwired grounding with citations at code
sites (§10), and the config (§11). This document records only what differs.

## Providers and liveness

A womb provider supplies the womb. Two exist by design:

- **Local** (this change): the womb sources run inside KAINE's Topos and Audition,
  selected by `[perception_feed].mode = "womb"`. Liveness uses the same discard-only
  probe the unattended gate uses for other feeds: read one frame and one audio block
  from the womb sources and drop them.
- **External** (Paracosmic, later): the body adapter streams the womb through the
  perception seam and publishes a content-free presence event, `gestation.womb`
  (source `gestation`, stream `gestation.out`, payload `{provider, frame_index}`),
  at least once per second. Liveness is a presence event within a bounded window
  (default 3 s) on the Redis clock.

`maturation-gate-liveness` 2.1 (womb before spawn) and 2.2 (womb loss) check this
interface and nothing else, so swapping the local provider for Paracosmic changes
config, not the gate.

## Single host

Everything the local provider computes is numpy on the CPU from `(seed, index)`:
no browser, no GPU renderer, no network service. The archived design's shared
ferrofluid parameter contract with `viz.js` is optional; the entity's pixels come from
the Python function only.

## Stream name

The readiness readout and the presence event both live on `gestation.out` (source
`gestation`), as the archived design specified. The gate runner's default readout
stream changes from `womb.out` to `gestation.out` in phase 3.

## Later: media in Paracosmic

The operator's design intent for Paracosmic: media play on in-world screens the
being may choose to watch or not, and its gaze is never fixed to them. The local
womb has no media; it is the gestation stimulus only.
