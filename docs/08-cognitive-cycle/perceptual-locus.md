# Where perception comes from

The perceptual locus is KAINE's model of which world its senses are bound to at any moment: the real room, a deterministic feed, or nothing. This page explains the locus values, the state files that carry them, the gates that control entity self-switching, and how sleep maintenance uses the same machinery. Read it if you operate the camera or microphone, change the perception or sleep code, or audit the privacy guarantee.

Related: [Audition](../09-modules/audition.md) · [Vision](../09-modules/vision.md) · [Sleep and maintenance](../10-sleep/README.md) · [Architecture](../02-architecture/README.md)

## Locus values

Three loci are defined in `kaine/perception_state.py`:

| Locus | Meaning | Real camera and microphone |
|-------|---------|---------------------------|
| `physical` | The entity perceives the room through the real microphone and camera | Allowed, subject to the desired-state flags |
| `virtual` | The entity perceives a configured feed: the deterministic perception feed (`seeded`, `playlist` or `stimulus_source`), or a screen or window capture (`[perception_feed].mode = "screen"`) | Forced off |
| `off` | No perception | Forced off |

Invalid locus strings are coerced at read time so the sensors are never left in an unknown state. Normally an invalid value becomes `physical`. Under a development lock it becomes `virtual`.

## State files

Two files under `state/perceptual_locus/` carry the locus state.

### `state/perceptual_locus/desired.json`

Written by `POST /diagnostics/perception/toggle` (audio and video desired flags), `POST /diagnostics/perception/locus` (locus and lock), the `PerceptualLocus` module, `select_virtual_feed()` at boot, the cycle's freeze watch, the sleep module when it suspends and restores perception, and the development gate. It holds the commanded state:

```json
{
  "audio_live_desired": false,
  "video_live_desired": false,
  "locus": "physical",
  "locus_locked": false,
  "locked_by": "operator"
}
```

The actual lock is the boolean `locus_locked`. `locked_by` records who holds the lock; it defaults to `"operator"`, is never `null`, and invalid values are coerced to `"operator"`. The perception tasks (`LiveMicrophone`, `LiveCamera`) poll this file and start or stop themselves to match.

### `state/perceptual_locus/runtime.json`

Written by the perception tasks on every start or stop. It is the source of truth for the dashboard on-air banner and sidecar observers:

```json
{
  "audio_live_active": false,
  "video_live_active": false,
  "audio_last_started_at": null,
  "video_last_started_at": null,
  "audio_last_stopped_at": null,
  "video_last_stopped_at": null
}
```

Both files contain only operational booleans, the locus string, the lock fields, and ISO-8601 timestamps. They never contain transcribed text, audio bytes, frame data, or any other sensory content.

## Effective capture logic

The helper functions in `kaine/perception_state.py` enforce the locus gate:

```python
def effective_audio_capture(path=None) -> bool:
    d = read_desired(path)
    return d.audio_live_desired and d.locus == "physical"

def effective_video_capture(path=None) -> bool:
    d = read_desired(path)
    return d.video_live_desired and d.locus == "physical"
```

Even if `audio_live_desired` or `video_live_desired` is `true`, the real sensors do not run unless the locus is `physical`.

`kaine/perception_state.py` also defines the virtual-locus mirrors:

```python
def effective_virtual_audio_capture(path=None) -> bool:
    d = read_desired(path)
    return d.audio_live_desired and d.locus == "virtual"

def effective_virtual_video_capture(path=None) -> bool:
    d = read_desired(path)
    return d.video_live_desired and d.locus == "virtual"
```

The [audition module](../09-modules/audition.md) and [vision module](../09-modules/vision.md) poll these mirrors exactly as the real-sensor tasks poll the physical functions. The same `audio_live_desired`/`video_live_desired` flags apply, so the operator mute toggle also works on the virtual feed.

`select_virtual_feed()` in `kaine/perception_state.py` is the boot-time helper that binds the entity to the `virtual` locus with both modalities desired. It is called when `[perception_feed].mode` is `seeded`, `playlist`, or `stimulus_source`. It honors `locus_locked`: if the locus is already locked, the configured feed is left unbound and the current desired state is returned unchanged.

## Operator-initiated locus switch

The dashboard endpoint `POST /diagnostics/perception/locus`, implemented in `kaine/dashboard/perception.py`, writes the new locus to `state/perceptual_locus/desired.json` directly via `write_desired_locus()`. This normally bypasses the entity self-switch gates. It does not bypass a development lock: when `locus_locked` is `true` and `locked_by` is `development`, every write from anyone other than the development holder is ignored, including operator writes. No bus event is published for an operator switch.

## Entity self-switch

`kaine/modules/perceptual_locus/module.py` contains `PerceptualLocus`, the module that handles entity-initiated locus switches. It watches `action_selection.out` for `intent.perceptual_locus.switch` intents and applies the `evaluate_locus_switch` gate.

This path is currently an unreachable producer gap. `PerceptualLocus` is a real consumer and the gate is tested, but nothing in the codebase emits `intent.perceptual_locus.switch`: the action selection module emits only `intent.speak`, `intent.think`, `intent.act`, and `intent.rest`. Until a producer lands, the entity cannot self-switch, and `allow_self_switch` should stay at its default of `false`. Locus changes are operator-driven.

```mermaid
flowchart TD
    A["intent.perceptual_locus.switch {locus: requested}"] --> B{"valid locus?"}
    B -- no --> C["Deny: invalid locus"]
    B -- yes --> D{"locus == current?"}
    D -- yes --> E["Deny: already in that locus"]
    D -- no --> F{"locus_locked?"}
    F -- yes --> G["Deny: locus locked by development gate,\nor locus locked by operator"]
    F -- no --> I{"allow_self_switch?"}
    I -- no --> J["Deny: self-switch disabled by policy"]
    I -- yes --> K{"inhibited?"}
    K -- yes --> L["Deny: inhibited"]
    K -- no --> M{"min_dwell_s elapsed?"}
    M -- no --> N["Deny: minimum dwell time not elapsed"]
    M -- yes --> O["Allow: write_desired_locus, publish perceptual_locus.changed"]
```

Gate parameters:

| Parameter | Default | Source |
|-----------|---------|--------|
| `allow_self_switch` | `false` | `PerceptualLocus` constructor |
| `min_dwell_s` | `30.0` | `PerceptualLocus` constructor |

On allow: `PerceptualLocus` writes `state/perceptual_locus/desired.json` with the new locus and publishes `perceptual_locus.changed` to `perceptual_locus.out`.

On deny: it publishes `perceptual_locus.denied` to `perceptual_locus.out` with the reason.

The entity cannot self-switch when:

- the cycle snapshot is inhibited,
- `locus_locked` is `true`,
- `allow_self_switch` is `false` (the shipped default), or
- the minimum dwell time since the last switch has not elapsed.

## Locus and sleep maintenance

External perception is suspended for the whole of every sleep, whatever modules are active, while the processors also suspend forward-model adaptation. During the developmental phase the developmental stimulus is the exception: it keeps playing through sleep (see the development lock below). The suspension uses the same locus machinery:

- `suspend_perception()` remembers the pre-sleep desired locus and, on playlist runs, pauses the shared playlist clock so the stimulus freezes at the same moment perception stops.
- `restore_perception()` is called in a `finally` block when the sleep ends, so it also runs after a failure or cancellation; it restores the remembered pre-sleep locus and resumes the playlist clock at the exact pause point.

Suspending perception keeps the entity from perceiving while it sleeps. The `finally` block means perception is never left suspended if the sleep pipeline raises, and pausing the playlist clock keeps the stimulus in step with the locus. If a development lock is active when sleep calls `write_desired_locus("off")`, the write is ignored because the development holder is the only writer allowed.

## Event types

| Event type | Stream | Condition |
|------------|--------|-----------|
| `perceptual_locus.changed` | `perceptual_locus.out` | Entity self-switch succeeded |
| `perceptual_locus.denied` | `perceptual_locus.out` | Entity self-switch denied |

Operator-initiated switches write directly to `state/perceptual_locus/desired.json` and do not emit a bus event.

## Zero-persistence invariant

All files under `state/perceptual_locus/` contain only:

- operational booleans (`audio_live_active`, `video_live_desired`, `locus_locked`, etc.),
- ISO-8601 start/stop timestamps,
- the locus string (`physical`, `virtual`, or `off`),
- the `locked_by` field.

They never contain transcribed text, audio bytes, video frames, or frame metadata. Raw camera frames from the [vision module](../09-modules/vision.md) and raw audio from the [audition module](../09-modules/audition.md) are processed in memory and released; no frame or sample touches disk.

## Virtual perception feed

Setting `locus = "virtual"` forces the real camera and microphone off through `effective_audio_capture` and `effective_video_capture`. The default locus is `physical`. A configured feed (seeded, playlist, stimulus source or screen) gives the vision and audition modules a source factory, and they then poll the virtual gates, so such a feed delivers only in the `virtual` locus.

The `virtual` locus is gated by `[perception_feed].mode`. The valid modes are `off`, `seeded`, `playlist`, `stimulus_source`, `live`, and `screen`. When the mode is `seeded`, `playlist` or `stimulus_source`, boot calls `select_virtual_feed()` to bind the entity directly into the `virtual` locus, provided the [audition module](../09-modules/audition.md) or [vision module](../09-modules/vision.md) is enabled. Boot does not do this for `screen`, so a screen feed delivers only once the operator sets the locus to `virtual`. The embodiment module (`kaine/modules/embodiment/`) is an unrelated embodiment control plane and is not required for virtual-locus availability.

Feeds that boot binds to the virtual locus:

- `seeded`: `SeededProceduralSource` in `kaine/modules/vision/feed.py`. Its `frame_at(frame_index)` is a pure function of `(seed, frame_index)`, so it has no time cutoff. It needs no external media, but it is procedural noise rather than naturalistic content.
- `playlist`: `PlaylistSource` in `kaine/modules/vision/feed.py`. This is the intended replacement for `seeded`: an operator-curated, openly licensed media corpus pinned by one checksummed manifest. A digest mismatch fails the run closed.
- `stimulus_source`: the developmental stimulus, a dim, low-contrast visual field and a filtered soundscape pulsed by a simulated maternal heartbeat, used during the developmental phase.

The offline experiment battery does not depend on these feeds. The planned live runs use the `playlist` feed with a reference film program pinned by its manifest.

## Configuration reference

The locus value itself (`physical`, `virtual`, or `off`) is set at runtime through the dashboard or, once a producer exists, the `PerceptualLocus` self-switch path. The `[perception]` section in `kaine.toml` configures the self-switch gate:

```toml
[perception]
allow_self_switch = false
min_dwell_s = 30.0
```

`boot.make_perception()` in `kaine/boot/factories/perceptual_locus.py` reads this section and passes the keys to the `PerceptualLocus` constructor.

The `PerceptualLocus` module is toggled via:

```toml
[modules]
perception = false   # shipped default; set true to enable PerceptualLocus
```

The `[modules].perceptual_locus` entry enables `PerceptualLocus`. The actual perception tasks (`LiveMicrophone`, `LiveCamera`) are part of the [audition module](../09-modules/audition.md) and [vision module](../09-modules/vision.md).

State files:

- `state/perceptual_locus/desired.json`: commanded locus, sensor flags, and lock
- `state/perceptual_locus/runtime.json`: live capture status

For `[perception_feed]` settings, see [Perception feed and sleep configuration](../appendix-a-configuration/perception-and-sleep.md).

## Key files

| File | Role |
|------|------|
| `kaine/perception_state.py` | `PerceptionState`, `DesiredState`, locus coercion, `effective_audio_capture`, `effective_video_capture`, `effective_virtual_*_capture`, `evaluate_locus_switch`, `select_virtual_feed` |
| `kaine/modules/perceptual_locus/module.py` | `PerceptualLocus`: entity self-switch gating and intent consumer |
| `kaine/modules/audition/` | `LiveMicrophone`: polls desired state through `effective_audio_capture`, or `effective_virtual_audio_capture` for a configured feed |
| `kaine/modules/vision/` | `LiveCamera`: polls desired state through `effective_video_capture`, or `effective_virtual_video_capture` for a configured feed |
| `kaine/dashboard/perception.py` | Operator perception endpoints |
| `state/perceptual_locus/desired.json` | Commanded locus, sensor flags, and lock |
| `state/perceptual_locus/runtime.json` | Live capture status |
