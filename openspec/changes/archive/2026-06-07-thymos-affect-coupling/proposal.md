## Why

`KAINE_Paper_v4.md` §3.3.3 specifies **direct affect coupling**: when Audition
detects emotion in a speaker's voice, Thymos's dimensional state shifts toward the
detected emotion with a **coupling coefficient modulated by Empatheia's
familiarity score** for that speaker — stronger familiarity, stronger coupling.
This is automatic emotional contagion (Hatfield et al. 1994), not mediated by
reasoning about the speaker's state. Today Thymos consumes Soma/Chronos/Mnemos but
**does not listen to speaker emotion at all**, so the entity's affect is unmoved
by the emotional tone of those it speaks with.

## What Changes

- Thymos subscribes to `audition.emotion` and `empatheia.agent_model`.
- On each `audition.emotion`, Thymos nudges its dimensional (valence/arousal/
  dominance) state toward the detected emotion's VAD coordinates by
  `coupling = coupling_base + coupling_familiarity_gain × familiarity`, clamped to
  a ceiling. With no Empatheia model yet, coupling falls back to `coupling_base`
  (graceful degradation).
- The nudge is applied directly to the dimensional state (pre-appraisal momentum),
  preserving Thymos's existing drift/hysteresis; it is **not** routed through the
  Scherer appraisal (the paper: "automatic; not mediated by reasoning").
- `[thymos]` config gains `[thymos.coupling]`: `coupling_base`,
  `coupling_familiarity_gain`, `coupling_ceiling`, `coupling_max_rate_per_s`,
  `enabled`.
- A cumulative-drift safeguard (`coupling_max_rate_per_s` rolling-window cap or
  equivalent cooldown) prevents sustained high-frequency extreme emotion events from
  pinning the dimensional state at a boundary.

## Capabilities

### New Capabilities

- `thymos-affect-coupling`: familiarity-modulated emotional contagion from
  detected speaker emotion into Thymos's dimensional state.

### Modified Capabilities

None expressed as deltas (existing appraisal/drives/state untouched; this adds a
coupling input).

## Impact

- **Depends on:** `thymos` (shipped), `rename-audition-vox` (consumes
  `audition.emotion`), `empatheia` (familiarity). Degrades gracefully if Empatheia
  is disabled (uses base coupling).
- **Repo:** updates `kaine/modules/thymos/`, tests, `config/kaine.toml`.
- **Welfare/safety:** coupling is bounded by `coupling_ceiling` (per-step cap) and
  a cumulative-drift safeguard (rolling-window rate cap or post-burst cooldown) so a
  hostile speaker cannot drive affect to an extreme over sustained exposure; sustained
  extreme affect is already a Welfare Event (paper §5.5).
- **State persistence:** the familiarity cache is serialized so coupling strength
  is not reset to cold on fork restore.
