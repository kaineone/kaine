## Why

The research-event pipeline silently drops data. The research-event observer's taxonomy, the raw bus archive, and the nexus diagnostics list each encode hand-maintained assumptions about module event types and payload fields that have drifted from what producers actually ship. Consequences, all verified with file:line evidence:

- No intent is ever recorded: `_TAXONOMY` keys `volition.intent`, but Volition publishes `intent.speak`/`intent.think`/`intent.act` — the entire record type is silently absent from the research log.
- Coalition metadata is always empty: the snapshot key read is `selected_events` but the cycle writes `selected`.
- Hypnos, Thymos, Topos, Chronos, and Audition records lose fields or entire streams to allowlist mismatches or missing taxonomy entries (`started_at`, `emotion`, phantom `horizon`/`topos.scene_change`, missing `chronos.out` and `chronos.report`, `f0_mean_hz`/`f0_std_hz`).
- The verbatim conversation archive archives no conversation: `lingua.out` has no producer; Lingua publishes `lingua.external`/`lingua.internal`.
- Three independently maintained "every module stream" lists have no drift test, guaranteeing recurrence.

Silent data loss is fatal for research admissibility: analyses and papers depending on the research log or archive are unknowingly built on incomplete data. The fix direction for every field/type mismatch is to adapt the consumer (taxonomy/allowlists) to the shipped producer payloads — producers have other consumers and their payloads are shipped reality; producer behavior must not change.

## What Changes

- Align the research-event observer taxonomy to real producer types and payload fields: key Volition intent types on `intent.speak`/`intent.think`/`intent.act`; read snapshot key `selected` for coalition metadata; allowlist Hypnos `started_at`, Thymos `emotion`, Audition `f0_mean_hz`/`f0_std_hz`; replace the Topos `topos.report` allowlist with `{prediction_error, normalised_error, change_score, habituation_score, alert}` and delete the producer-less `topos.scene_change` entry.
- Add the missing Chronos stream: add `chronos.out` to `_CURATED_STREAMS` and a `chronos.report` taxonomy entry allowlisting only content-free scalars `{anomaly_score, habituation_score, rumination_detected, temporal_prediction_error, time_since_last_interaction_s}` — excluding `temporal_context` and `feature_vector` (latent content).
- Fix the raw bus archive: replace the phantom `lingua.out` with the real `lingua.external` and `lingua.internal` streams.
- Introduce a canonical module-stream registry derived from registered module names via `module_stream(name)` (with documented exclusions, e.g., Lingua's extra internal streams), and add a drift test that diffs each of the three hand-maintained lists (`_CURATED_STREAMS`, `_MODULE_OUT_STREAMS`, `DEFAULT_DIAGNOSTICS_STREAMS`) against it, following the shared-logic precedent of `welfare_observer.py`.
- Thread the profile through `load_evaluation_config` / `load_research_event_log_config` so a profile's `[evaluation]` block takes effect consistently with the research gate.
- Wire `[volition].interrupt_threshold` from config into the report policy so the merged interruptible-utterance feature is reachable.
- Remove five unused imports flagged by CodeQL.

Every fix ships with a regression test built from the real producer payload shapes, so the test re-breaks if either side drifts. Producers are unchanged; no latent vectors, text, or transcripts enter any allowlist.

## Impact

- Spec: none affected (no capability requirement changes); the change restores event capture the specs already assume.
- Code: `kaine/evaluation/observers/research_event_observer.py`, `kaine/evaluation/observers/raw_bus_archive_consumer.py`, `kaine/nexus/__main__.py` (+ new shared registry module), `kaine/evaluation/config.py`, `kaine/cycle/__main__.py`, benchmark/test modules (import removals only).
- Docs: present-tense notes on the canonical stream registry, taxonomy/allowlist conventions, and the content-free constraint for the research log.
- Risk: low — all changes are consumer-side allowlists, config threading, and dead-import removal; drift tests make future regressions loud instead of silent.
