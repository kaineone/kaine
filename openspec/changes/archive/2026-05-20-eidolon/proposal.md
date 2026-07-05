## Why

`docs/kaine-paper.md` §3.2 places Eidolon as the self-model: "maintains a
persistent store of values, behavioral norms, capability map, personality
baseline, and identity history that starts empty and fills through
observation of the system's own patterns over time." Build prompt §3.3
also calls for a "drift detector comparing recent patterns against
history." Eidolon is the third and final Phase 3 module; with it,
`v0.3-cognition` ships.

The build prompt is explicit: values start empty. Eidolon does not
prescribe an identity; it discovers one through observation. The drift
detector exists not to police the entity but to make change *visible*
rather than invisible — the system notices when it is becoming
someone different.

## What Changes

- Introduce `kaine.modules.eidolon` package split four files:
  - `document.py` — `SelfModel` dataclass with `values`,
    `behavioral_norms`, `capability_map`, `personality_baseline`,
    `identity_history`, `internal_speech_count`. JSON-serializable.
    Load/save helpers around a configurable on-disk path.
  - `drift.py` — `DriftDetector` protocol + `SourceDistributionDrift`
    default. Maintains two histograms (recent window + historical
    cumulative) of workspace-broadcast source frequencies; reports
    drift as the symmetric Kullback–Leibler-ish divergence between
    them. Threshold-based flagging.
  - `module.py` — `Eidolon(BaseModule)` subscribing to the workspace
    broadcast + a configurable internal-speech stream
    (`lingua.internal` by default, will be wired by Phase 5.2).
    Every broadcast updates the drift detector. When divergence
    exceeds threshold, publishes an `eidolon.drift` event.
    Periodically persists the SelfModel to disk.
  - `__init__.py` — package exports.
- `[eidolon]` block in `config/kaine.toml`: persistence path, drift
  window size, drift threshold, save interval, internal-speech stream,
  baseline/alert salience. `modules.eidolon = false`.
- State persistence: `state/eidolon/self_model.json` (gitignored under
  the existing `state/` pattern). The file is rewritten atomically
  (write to `.tmp` then `os.replace`).
- Tests: pure Python, no external deps; cover dataclass roundtrip,
  drift math, module wiring.

## Capabilities

### New Capabilities

- `eidolon`: persistent self-model with drift detection. Owns the
  SelfModel document, the source-distribution drift detector, and the
  periodic save loop.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus`, `module-pattern`, `cognitive-cycle`.
  All shipped.
- **Repo:** adds `kaine/modules/eidolon/*.py`, `tests/test_eidolon_*`,
  updates `pyproject.toml` (packages list), `config/kaine.toml`,
  `.gitignore` (`state/`).
- **Disk:** `state/eidolon/self_model.json` grows slowly — capped
  identity history (default keep last 256 snapshots).
- **No runtime impact** on the cycle. Eidolon is registered in code
  paths but not auto-added to ModuleRegistry; first boot decides.

After this change Phase 3 closes and `v0.3-cognition` is tagged on
main.
