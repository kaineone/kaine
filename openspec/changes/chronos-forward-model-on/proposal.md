## Why

The paper says Chronos "publishes temporal prediction errors" and "reads the broadcast as a bottom-up observation it predicts". In the base-thesis profile the forward-prediction head is off, so `temporal_prediction_error` is always 0.0 and Chronos alerts only through the rolling z-score and rumination detectors. The head already exists, adapts online, suspends adaptation during sleep and persists with the being (`chronos/module.py` `serialize`), so the gap is a configuration gap, not missing code.

Two defects sit in the input Chronos times:

- **Every `audition.out` entry counts as an interaction.** `_user_input_loop` resets the interaction clock on any entry of a configured stream. With general audition on, `audition.perception` arrives about twice a second, so `time_since_last_interaction_s` stays near zero, and Thymos's social drive (`tsli / social_drive_time_scale_s`) never builds. Film dialogue on the playlist feed resets it too, although nobody is addressing the entity.
- **Audition has no featurizer bin.** The featurizer's eight known sources predate the Audition rename and omit `audition`, so Audition's events land in the overflow bin, which is also Praxis's bin (`chronos/featurizer.py`).

The capability spec is also stale: it still names `audio_in.out` as the default user-input stream, while the code and `config/kaine.toml` use `audition.out` since the Audition rename.

## What Changes

- **Forward prediction on in the thesis profile.** `config/profiles/thesis_test.toml` sets `[chronos].forward_prediction = true`. The shipped `config/kaine.toml` keeps it off (every module ships off). The operator overlay is gitignored, so the operator sets the same key there by hand; the PR says so.
- **Only operator speech counts as interaction.** Chronos decodes each entry on its user-input streams and resets the interaction clock only for speech heard on an operator channel:
  - the event type is `audition.transcription` (with non-empty text) or `audition.emotion`. Base-thesis runs with transcription off, so operator speech reaches Chronos only as `audition.emotion`;
  - the event's `source_label` is an operator source. The operator-source list (`live_mic`, `microphone`, `remote`) moves from its two copies in `workspace/volition.py` and `modules/empatheia/module.py` into one shared constant that all three import;
  - `audition.perception`, `audition.prosody` and speech from the seeded, playlist, womb and screen feeds never reset the clock.

  `[chronos]` gains `interaction_event_types` to override the event types; the source list stays shared, not per-module.
- **Audition gets its own featurizer bin, behind a versioned layout.**
  - Layout 1 is today's: eight source bins, unknown sources in the last bin, slot 23 always zero.
  - Layout 2 keeps the 24-dimension vector and puts `audition` in slot 23, the slot reserved for a future feature.
  - The layout version is part of Chronos's serialized state. A snapshot without it is layout 1, so every preserved being revives with the layout its network and head were trained on. Only a new being, one with no Chronos state, starts on layout 2.
  - The vector length does not change, so neither the CfC, the head nor the `chronos.network` plugin seam changes shape.
- **Spec catch-up.** The chronos spec names `audition.out` as the default user-input stream.

## Capabilities

### Modified Capabilities

- `chronos`: interaction counting, the default user-input stream, featurization layout versioning.
- `chronos-predictive`: the thesis profile enables the forward head.

## Impact

- **Code:** `kaine/modules/chronos/module.py`, `kaine/modules/chronos/featurizer.py`, `kaine/boot/factories/chronos.py`, the shared operator-source constant and its two existing users.
- **Config:** `config/profiles/thesis_test.toml` (sequenced through the integrator), a commented `interaction_event_types` default in `config/kaine.toml`.
- **Preserved beings:** revive unchanged on layout 1. No weights are reset.
- **Research impact:** in base-thesis runs, Chronos starts publishing a non-zero temporal prediction error, which feeds anomaly salience, and the interaction clock no longer resets on perception events. Both change what competes in the workspace and the social drive, so the next study is re-baselined with them in place. No study is running.
- **Paper:** none. The change brings the code to what the paper already says.
