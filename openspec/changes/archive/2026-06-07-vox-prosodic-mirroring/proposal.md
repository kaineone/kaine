## Why

`KAINE_Paper_v4.md` §3.3.4 specifies that Vox "additionally implements prosodic
mirroring: a residual of the detected speaker's prosody blends with the entity's
own affect-driven parameters, producing vocal accommodation toward the
conversational partner." Today Vox derives Chatterbox parameters purely from
Thymos affect; there is no path from a speaker's prosody into the entity's voice,
so KAINE does not accommodate to who it is speaking with.

This change depends on `audition.prosody` (from `audition-forward-model`).

## What Changes

- Vox subscribes to `audition.prosody` and caches the latest speaker prosody
  features. `audition.prosody` carries **librosa-derived** numeric features (F0
  summary, RMS energy, speaking rate) produced by Audition (`audition-forward-model`
  change); no parselmouth dependency is introduced anywhere in this change.
- `kaine/modules/vox/mirroring.py`: blends a bounded **residual** of the speaker's
  prosody (pace, pitch range / expressivity) into the affect-driven
  `ChatterboxParams` produced by the existing `affect_to_*` mapping. The entity's
  own affect remains primary; the mirror is a small accommodation, controlled by
  `mirror_strength` ∈ [0, mirror_ceiling].
- `[vox]` config gains `[vox.mirroring]`: `enabled`, `mirror_strength`,
  `mirror_ceiling`, `decay_s` (mirror fades when the partner stops speaking).

## Capabilities

### New Capabilities

- `vox-prosodic-mirroring`: bounded accommodation of synthesized prosody toward a
  detected speaker's prosody, on top of affect-driven parameters.

### Modified Capabilities

None expressed as deltas (the affect→params mapping is unchanged; mirroring is a
post-blend).

## Impact

- **Depends on:** `vox` (renamed `audio-output`), `audition-prosody`
  (`audition.prosody`). Degrades gracefully (no prosody seen → affect-only voice).
- **Repo:** updates `kaine/modules/vox/`, tests, `config/kaine.toml`.
- **Identity:** affect stays primary so mirroring does not erase the entity's own
  voice; the residual is bounded and decays — accommodation, not impersonation.
