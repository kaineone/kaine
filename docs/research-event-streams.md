# Canonical module-stream registry & research-event taxonomy

## Canonical registry (task: never-drift)

`kaine/evaluation/stream_registry.py` is the single source of truth for the
module-stream set. It derives stream names from the canonical module-name
tuple via `kaine.bus.schema.module_stream` (it does NOT import
`kaine.modules` — the import-boundary contract forbids `kaine.evaluation`
importing it; the static name tuple is therefore deliberate).

Three consumers derive their stream lists from the registry:

- `_CURATED_STREAMS` (research_event_observer.py) → `curated_module_streams()`
- `_MODULE_OUT_STREAMS` (raw_bus_archive_consumer.py) → `raw_archive_module_streams()`
- `DEFAULT_DIAGNOSTICS_STREAMS` (kaine/nexus/__main__.py) → `diagnostics_streams()`

### Documented exclusions / extras

- **Lingua split**: there is no single `lingua.out` producer — Lingua
  deliberately publishes `lingua.external` and `lingua.internal`
  (kaine/modules/lingua/module.py). Every list expands `lingua.out` into that
  split.
- **Curated research log** additionally excludes `vox.out` (raw audio
  content) and Lingua streams (transcripts) — the log stays content-free.
- **Nexus diagnostics** additionally excludes the low-signal operational
  streams (`volition.out`, `mundus.out`, `perception.out`, `welfare.out`,
  `preservation.out`, `individuation.out`) and prepends/appends the
  non-module entries `cycle.tick` (event type) and `workspace.broadcast`.

### Drift-test contract

`tests/test_stream_registry_drift.py` asserts each of the three consumer
lists **exactly** equals the registry-derived set (set equality, not subset).
Adding a module or a stream to one list without the registry fails the test;
adding to the registry propagates to all three consumers automatically.

## Taxonomy / allowlist conventions

- **Consumers adapt to shipped producer payloads.** The taxonomy keys and
  field allowlists describe what producers actually emit today
  (e.g. `intent.speak`/`intent.think`/`intent.act` from
  `kaine/workspace/volition.py`, `hypnos.sleep.started` `started_at`,
  `thymos.emotion` `emotion`, `topos.report`'s five content-free scalars,
  `audition.prosody` `f0_mean_hz`/`f0_std_hz`, `chronos.report`). Exact keys
  for the intent family — no prefix matching; unknown subtypes are not logged.
- **The research log is content-free.** No latent vectors
  (`temporal_context`, `feature_vector`), no transcripts
  (`audition.transcription` is intentionally absent from the taxonomy), no
  raw audio. A regression test loops over the entire taxonomy asserting no
  latent field name ever appears in any allowlist.
- Adding a payload field to a record requires a deliberate taxonomy edit —
  keys not in the allowlist are dropped, and event types not in the taxonomy
  produce no record at all.
