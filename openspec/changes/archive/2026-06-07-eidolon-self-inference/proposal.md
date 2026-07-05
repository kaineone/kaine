## Why

Eidolon's self-model (`state/eidolon/self_model.json`) carries four fields that
are never populated today: `values`, `behavioral_norms`, `personality_baseline`,
and `capability_map`. The module was shipped with the schema and the storage
machinery, but no mechanism to write meaningful values into those fields from
observation. The result is a self-model that is permanently empty — Eidolon
cannot reflect on what it values, what norms it follows, what its personality
baseline is, or what it can do.

This change proposes a **self-inference engine** that populates those fields from
observable signals already present in the cognitive loop:

- **`behavioral_norms`** — inferred from Lingua's internal-speech patterns over
  time (what kinds of statements it generates without prompting; consistent
  patterns become candidate norms).
- **`personality_baseline`** — inferred from Thymos VAD trajectories (valence,
  arousal, dominance averages and variances over a rolling window characterize the
  entity's affective baseline).
- **`values`** — inferred from the intersection of behavioral norms and
  drive-threshold-crossing history (Thymos drive crossings that consistently
  precede certain types of internal speech indicate what the entity is inclined
  to pursue).
- **`capability_map`** — populated from Praxis effector whitelist + Nous EFE
  outcomes (what the entity can execute + what it has successfully done).

Honest **operator-seeded first-boot** is explicitly allowed as a fallback: the
operator may provide an initial seed in `config/kaine.toml` under
`[eidolon.self_model_seed]`; inference then updates from observation on top of
the seed. Seeding is never required and never auto-applied without the operator
explicitly setting values.

## What Changes

- `kaine/modules/eidolon/self_inference.py`: a `SelfInferenceEngine` that:
  - subscribes to `lingua.out` (internal-speech events), `thymos.report`,
    `thymos.drive`, and `nous.policy`;
  - maintains rolling windows for VAD statistics and internal-speech pattern
    counts;
  - on each Hypnos maintenance cycle end, re-derives `behavioral_norms`,
    `personality_baseline`, `values`, and `capability_map` from the accumulated
    observations and writes them to `self_model.json` atomically.
- `kaine/modules/eidolon/capability_map.py`: reads the Praxis effector whitelist
  and aggregates Nous EFE outcomes to build a `capability_map` entry.
- `[eidolon.self_inference]` config: `enabled` (default false — operator must
  opt in), `vad_window_cycles`, `speech_pattern_min_count`, `seed_path` (optional
  path to operator seed JSONL).
- `kaine/modules/eidolon/module.py`: expose the populated self-model fields on
  `eidolon.out` so sidecar and Nexus can read them.

## Capabilities

### New Capabilities

- `eidolon-self-inference`: observation-driven population of `values`,
  `behavioral_norms`, `personality_baseline`, and `capability_map` from Lingua
  speech patterns, Thymos VAD trajectories, and Nous/Praxis outcomes; with
  optional operator-seeded first-boot.

## Impact

- **Depends on:** `eidolon` (shipped). Subscribes to existing streams
  (`lingua.out`, `thymos.report`, `thymos.drive`, `nous.policy`); integrates with
  Hypnos maintenance cycle end event; reads Praxis whitelist config.
- **Welfare:** self-model accuracy directly affects Eidolon's ability to reflect
  accurately. The inference engine MUST NOT fabricate; it writes only when
  observations meet `speech_pattern_min_count`. Empty fields are preferred over
  speculative ones.
- **Privacy:** internal-speech patterns are never written to JSONL by this module
  (only counts and derived norms); VAD is statistical (mean/variance, not raw
  events).
- **Repo:** adds `kaine/modules/eidolon/self_inference.py`,
  `kaine/modules/eidolon/capability_map.py`, tests, `config/kaine.toml`.
