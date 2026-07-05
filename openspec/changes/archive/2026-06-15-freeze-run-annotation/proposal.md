# freeze-run-annotation

## Why

When Spot's crash-handler fires during a run (detect → freeze → snapshot →
restart → escalate), the freeze is invisible to research analysis. Today Spot
only publishes ephemeral `spot.status` / `spot.log` bus events (a Redis ring
buffer trimmed on every publish) and writes a separate, isolated
`state/cycle/incidents/` JSONL. Nothing reaches the curated research event log
(`data/evaluation/research_events/`), and there is no run-level cross-link, so a
run whose data was collected across a module crash carries no record that an
interruption occurred. An analyst reading the research log cannot tell that the
entity was suspended mid-run, nor join the interruption to the durable incident
provenance.

The research observer's taxonomy already reserves a `spot.incident` entry (and a
`spot.incident.*` prefix match), but **no producer publishes `spot.incident`** —
the annotation path is dead. This change closes the loop: Spot publishes a
structured `spot.incident` bus event at each lifecycle transition, the research
observer captures it (privacy-filtered), and the A1 sink stamping stamps the
captured record with `run_id` — establishing the run↔incident cross-link, keyed
to the incident by `incident_id`.

## What Changes

- **Spot publishes a structured `spot.incident` bus event** at each lifecycle
  transition (detect, freeze, snapshot, restart, escalate), carrying
  `incident_id`, `transition`, `module`, `fault_class`, and the
  transition-specific operational fields already recorded in the incident_log
  record. Published via the same `_publish` path Spot already uses (source
  `"spot"`, type `"spot.incident"`), IN ADDITION to the existing
  `spot.status` / `spot.log` events (which are unchanged). Operator filesystem
  paths in any free-text are scrubbed via the existing incident_log scrubber.
- **Cycle-position / tick↔poll bridge.** The event always carries Spot's
  `poll_index`; it also carries the cycle's `tick_index` when Spot can read it.
  `__main__.py` wires a best-effort `tick_index_provider` callable (reading
  `CognitiveCycle.tick_index`) into Spot at construction.
- **Research observer captures `spot.incident`** (and the `spot.incident.*`
  prefix family) into a privacy-filtered record carrying the fields above, so it
  lands in `data/evaluation/research_events/` stamped with `run_id` and carrying
  `incident_id`.
- The separate `state/cycle/incidents/` durable incident log is **unchanged** —
  it remains the rich isolated provenance; this change only adds the
  bus-event path into the research log.

## Impact

- Affected specs: `spot-supervisor` (ADDED requirements).
- Affected code: `kaine/cycle/spot.py` (new `spot.incident` publishes +
  `tick_index_provider`), `kaine/cycle/__main__.py` (wire the provider),
  `kaine/evaluation/observers/research_event_observer.py` (taxonomy field
  alignment + record construction for `spot.incident`).
- No new config keys. No change to the durable incident log, to
  `spot.status` / `spot.log`, or to module/cycle behavior.
