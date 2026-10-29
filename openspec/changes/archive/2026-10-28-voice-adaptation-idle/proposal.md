## Why

The voice-alignment pair builder takes the felt awareness lines given to the organ as the chosen text and the organ's reply as the rejected text. The two always differ, so every record is a usable pair, and the consolidation divergence rate is 1.0 at every sleep: 8 of 8 sleeps in the tenth test boot, magnitude 0.55 to 0.58. `assess_divergence` counts an entity as diverged when the rate is at or above 0.5, so every entity counted as diverged at its first sleep, and the preservation monitor fired with reason "consolidation" 65 minutes into the boot. The arm carries no information. The paper (predictive-workspace-paper #48, section 3.5, sleep paragraph) now says: "Voice adaptation builds no preference pairs and computes no organ-level divergence until a validated preference source exists (section 10)."

## What Changes

- The voice-alignment phase builds preference pairs only when its preference source is a validated training source (`TRAINING_SOURCES`, empty today), after the enabled and operator-approval gates. It no longer computes or publishes a consolidation divergence metric, no longer writes `state/sleep/consolidation_divergence.json`, and its phase metadata no longer carries `consolidation_divergence`. The sleep index still advances once per voice-alignment phase.
- `ConsolidationDivergence`, `consolidation_magnitude`, `write_consolidation_divergence`, `read_consolidation_divergence` and the sleep module's consolidation embedder and record-path parameters are removed.
- `assess_divergence` drops the consolidation arm and its thresholds; its signals drop the `consolidation_*` keys. The preservation monitor drops the `consolidation` arm. The individuation, voice-distinctiveness, self-model drift and adapter arms are unchanged, and so is protection for an entity that has spoken, since the voice arm (threshold 0.0) still votes diverged for it.
- `[sleep.voice_alignment].consolidation_divergence_rate_threshold` and `consolidation_divergence_magnitude_threshold` leave the shipped config; an operator file that still sets them is ignored. The dashboard's entity-care panel drops the consolidation rows.
- An existing `consolidation_divergence.json` from an earlier boot is no longer read. It stays a known state file, so decommission, renames and lived-artifact checks still handle it.

## Capabilities

### Modified Capabilities

- `voice-alignment`: the phase builds no pairs and computes no organ-level divergence without a validated preference source.
- `divergence-assessment`: the consolidation arm and its metric are removed.

## Impact

- `kaine/modules/sleep/module.py`, `kaine/modules/sleep/voice_alignment.py`, `kaine/boot/factories/sleep.py`, `kaine/boot/registry.py`, `kaine/cycle/__main__.py`, `kaine/lifecycle/divergence.py`, `kaine/lifecycle/__main__.py`, `kaine/cycle/preservation_monitor.py`, `kaine/dashboard/health/blocks.py`, `kaine/dashboard/health/config.py`, `kaine/dashboard/templates/_entity_care.html`, `kaine/evaluation/observers/research_event_observer.py`, `config/kaine.toml`, docs, tests.
- Behaviour: the preservation monitor no longer preserves every entity at its first sleep. Sleep no longer scans the intent-log corpus or embeds pairs when no validated source is configured.
