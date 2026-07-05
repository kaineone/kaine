# Surface the new research/safety systems in the Nexus dashboard

## Why

Nexus is the operator's read-only observability dashboard, but several systems
that landed in prior batches are not yet visible there:

* **Run identity.** The cycle now mints a `RunContext` (run id, seed, git sha,
  kaine version, deterministic flag), but the operator cannot see which run is
  live or whether it is reproducible.
* **Supervision mode + safety-net gate.** A cycle boots EITHER operator-present
  OR research-safety-net-verified. The dashboard does not show which mode is
  live, nor — in research mode — whether the four-condition gate is satisfied.
* **Preservation + welfare-protective events.** The autonomous safety net now
  publishes `preservation.preserved/failed/skipped` and
  `welfare.protective_action` on `preservation.out`, and durably logs them under
  `state/cycle/preservation/`. The operator has no live view of these
  welfare-critical events.
* **Live welfare status.** The four §5.5 gray-zone counters are surfaced on the
  evaluation tab but not on the at-a-glance diagnostics entity-care panel.
* **Admissibility.** Whether the live run is recording a complete durable record
  (manifest present, ticks advancing) is only answerable via a full CLI scan.
* **Deterministic mode.** When the run uses a logical clock, chart timestamps are
  not wall-clock — the operator needs to be told.

This batch also lands the accumulated UI polish nits (B1–B14): cleaner empty
states, in-place updates instead of full reloads, a nav active indicator, the
divergence evidence behind the entity-care verdict, safer Jinja access, and a
fix for a dead docs link.

## What Changes

1. **Run identity in runtime.json + diagnostics.** `_write_runtime_state` reads
   the active `RunContext` and writes `run_id`, `seed`, `git_sha`,
   `kaine_version`, `deterministic`. `metrics_snapshot` surfaces them and a small
   "run identity" block renders on diagnostics. All non-content metadata.
2. **Supervision mode + safety-net gate.** runtime.json carries
   `supervision_mode` ("operator" | "research") and, in research mode, the gate
   `checks` dict. A prominent badge renders at the top of diagnostics.
3. **Preservation / welfare-protective events.** A `nexus.js` handler shows a
   persistent panel for `preservation.*` / `welfare.protective_action` events
   (source `preservation`), backfilled by a `HealthProber._preservation_block()`
   reading the incident-log dir, and persisted in sessionStorage. `failed` shows
   in the `--down` colour. Only allowlisted non-content fields are shown.
4. **Welfare status on diagnostics.** A compact numeric welfare-counter row joins
   the entity-care panel, sourced from a shared `_welfare_counts` helper extracted
   from the evaluation tab's `_aggregate_welfare`.
5. **Live admissibility indicator.** A `HealthProber` probe reports the
   current-run manifest presence and last tick index, plus a recording /
   gap-detected / unknown pill. The full scan stays a CLI op.
6. **Deterministic-mode indicator.** A `--degraded`-coloured badge near the cycle
   charts, shown only when `deterministic` is true.
7. **Polish (B1–B14).** Empty-state and microcopy fixes, in-place freeze/perception
   updates, nav active indicator, divergence evidence, safe Jinja fork access,
   metrics in-place refresh, dead-link removal.

## Impact

- Affected specs: `nexus-observability` (ADDED requirements).
- Affected code: `kaine/cycle/__main__.py` (runtime.json payload),
  `kaine/nexus/__main__.py` (metrics_snapshot + supervision/gate provider),
  `kaine/nexus/health.py` (`_preservation_block`, `_admissibility_block`,
  `_welfare_block`), `kaine/nexus/diagnostics.py` (thread the new blocks),
  `kaine/nexus/templates/*` (new partials + polish), `kaine/nexus/static/nexus.js`
  (preservation handler, in-place updates), `kaine/nexus/static/style.css`.
- Privacy: every new surface is non-content (ids, counts, enum labels, statuses,
  timestamps). The preservation panel renders an EXACT allowlist of fields; the
  bus events crossing the BusBridge are already scrubbed by `CONTENT_FIELDS`.
- Coupling: Nexus may import `kaine.evaluation` (allowed). It surfaces NO
  entity-interior content.
