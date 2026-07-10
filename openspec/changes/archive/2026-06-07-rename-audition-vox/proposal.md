## Why

`KAINE_Paper_v4.md` §3.3.1 names the hearing module **Audition** (currently
`audio_in`) and §3.3.4 names the voice module **Vox** (currently `audio_out`).
These are the paper's canonical names for the perception/expression organs, and
every new v4 workstream references them (Thymos affect coupling consumes
Audition's emotion events; Vox prosodic mirroring blends Audition's prosody).

This change does the rename **first, on a clean base**, so all subsequent v4
code is written against the final names rather than renaming churn later. It is
a pure rename: no behavior changes, no new capability. Doing it before the rest
of v4 avoids ~445 references of conflicting churn mid-stream.

## What Changes

- Rename package `kaine/modules/audio_in/` → `kaine/modules/audition/`; class
  `AudioInput` → `Audition`; `name = "audio_in"` → `name = "audition"`.
- Rename package `kaine/modules/audio_out/` → `kaine/modules/vox/`; class
  `AudioOutput` → `Vox`; `name = "audio_out"` → `name = "vox"`.
- Rename bus event types: `audio.in.transcription` → `audition.transcription`,
  `audio.in.emotion` → `audition.emotion`, `audio.out.synthesized` →
  `vox.synthesized`. Stream names follow the module name (`audition.out`,
  `vox.out`).
- Update `boot.py` factories `make_audio_in`/`make_audio_out` →
  `make_audition`/`make_vox` and the `SIMPLE_FACTORIES` keys.
- Update `config/kaine.toml` sections `[audio_in]`/`[audio_out]` → `[audition]`/
  `[vox]` and the `[modules]` toggles.
- Update `kaine/workspace/volition.py` constants
  (`USER_COMMUNICATION_SOURCE`, `USER_COMMUNICATION_TYPE`,
  `OWN_EXTERNAL_SPEECH_*`) to the new names.
- Update Nexus stream lists and health probes (`kaine/nexus/`).
- Rename test files and update all references.
- State sink directory `state/audio_out/` → `state/vox/`.

## Capabilities

### New Capabilities

- `audition`: the hearing organ's module identity, stream, and event-type names
  after the rename from `audio_in`.
- `vox`: the voice organ's module identity, stream, and event-type names after
  the rename from `audio_out`.

### Modified Capabilities

None (behavior is unchanged; only names change).

## Impact

- **Depends on:** `audio-input`, `audio-output` (shipped). Should land after the
  open PR stack (audio-out-playback → language-organ → reference-body-embodiment)
  merges to avoid conflicts.
- **Repo:** renames two packages, two config sections, ~20 test files, Nexus
  references, volition constants. ~445 reference sites.
- **Bus contract:** event-type strings change. Every producer/consumer of the
  audio.* types is updated atomically in this change so no consumer is left
  reading a dead type.
- **No runtime/behavior impact:** modules ship disabled-by-default as before.
