# Mundus

Mundus is KAINE's body-agnostic embodiment layer. It routes perception from a body into the workspace as `mundus.*` events and routes the entity's action intents back to the body, through one pluggable adapter per body. It draws on internal forward models of the body (Wolpert, Ghahramani, and Jordan 1995): its continuous control surface closes the loop with an efference copy fed to a forward model. Read this page if you are enabling a body, building an adapter, or checking the embodiment gates.

## Status and gates

Mundus is built and tested, and held: it is off in the shipped `config/kaine.toml` and in the base-thesis `thesis_test` profile. It acts on a body only when all three of these hold:

1. `[modules].mundus = true` in the operator file `config/kaine.operator.toml`, so the module is constructed (the same flag in the shipped `config/kaine.toml` is overridden by the `thesis_test` profile);
2. `[mundus].enabled = true` (the shipped value), the configuration gate;
3. `KAINE_MUNDUS_OPERATOR_APPROVED=1` in the environment, the operator gate.

`_enabled()` is false unless both the configuration flag and the environment variable are set. With either missing, Mundus logs which gate failed and `initialize()` returns without opening the body.

No transport-backed adapter exists yet. The included adapter is a transport-free stub that pins the protocol locally, so on the reference host Mundus has no body to perceive or act through. It is therefore not in the default order of the [module-addition study](../15-experiments/ignition-study.md) (the ignition study in code), where it would be an expected null; it joins the study only once a body is attached, through an explicit `--order`. The planned experiment asks whether motor-contingency learning through the control surface, following a freeze-then-free motor curriculum (Bernstein 1967) and treating perception as sensorimotor mastery (O'Regan and Noë 2001), changes the workspace's dynamics. To build a body adapter, see [Building embodiment adapters for Mundus](../20-embodiment-adapters.md).

`probe_available()` checks whether activation is possible, `activate()` starts the feed, intent and speech loops, and `set_dormant()` holds them for the next `initialize()`. While a being is gestating, boot holds Mundus dormant (it is listed in `GESTATION_DORMANT_EFFECTORS` with Vox), and the gate runner activates it at birth. Otherwise `initialize()` opens the body as soon as the gates pass.

Continuous motor control can be produced but is off, and nothing drives it at runtime. The control surface ships off (`[mundus.control_surface].enabled = false`), its default policy emits nothing, and continuous channels are unexposed by default. The symbolic verb families, such as `move`, `turn` and `say`, have no learned producer and remain operator tools.

## What it does

The Mundus core constructs and drives exactly one `EmbodimentAdapter` and reads the adapter's capability descriptor instead of hard-coding any platform. It:

- turns feed frames from `adapter.feed()` into `mundus.*` events, applying the intensity policy and removing the raw sense buffers named in the descriptor before anything reaches the bus;
- forwards symbolic `intent.avatar.<family>` intents from the Volition stream to the adapter's symbolic sink, gated by the perception locus and by per-family exposure;
- routes `intent.avatar.control` to the adapter's continuous sink, gated by the locus and by per-channel exposure, and publishes an efference copy on `mundus.efference`;
- mirrors the entity's external speech (`lingua.external`) into the body's local chat when `mirror_speech` is true.

All body I/O runs in its own asyncio tasks, and bus publishes do not block the cycle.

## The adapter contract

An `EmbodimentAdapter` (`kaine/modules/mundus/adapter.py`) has a narrow interface:

| Method or property | Purpose |
|---|---|
| `capabilities()` | Returns an immutable `EmbodimentCapabilities` descriptor: each feed kind with its bus event and baseline intensity, the symbolic action families with their default exposure, the continuous channels, the raw-buffer payload keys, and whether the body is `transitional` |
| `open()` / `close()` | The adapter owns its transport |
| `feed()` | Async iterator of `FeedFrame(kind, payload)`; the adapter never publishes to the bus itself |
| `apply_action(family, params)` | Symbolic sink for verbs |
| `apply_setpoints(channels)` | Continuous sink; a body with no continuous channels returns `False` |

The canonical continuous channels are `drive`, `yaw_rate`, `gaze_yaw`, `gaze_pitch` and `interact`. Locomotion and gaze rates are clamped to [−1, 1] and `interact` to [0, 1].

## Inputs

| Stream | Event or mechanism | Description |
|---|---|---|
| `adapter.feed()` | `_feed_loop` and `_handle_feed` | Perception frames from the body |
| `volition.out` | `_intent_loop`, then `_send_action` | `intent.avatar.<family>` verbs to `apply_action` |
| `volition.out` | `_intent_loop`, then `_drive_control` | `intent.avatar.control` to `apply_setpoints`, clamped and gated, plus a `mundus.efference` copy |
| `lingua.external` | `_speech_loop` (if `mirror_speech = true`) | Text sent as a `say` action to local chat |

## Outputs

### Bus events

The active adapter's descriptor maps feed kinds to events and baseline intensities. The stub declares `chat` as `mundus.chat` at 0.6 and `proprio` as `mundus.proprio` at 0.3. The core applies the same intensity policy and raw-buffer removal to whatever a descriptor declares:

| Event | Source frame | Baseline intensity | Policy | Notes |
|---|---|---|---|---|
| `mundus.proprio` | `proprio` | from the descriptor | 0.8 if `dying` or `falling` | No payload schema ships |
| `mundus.chat` | `chat` | from the descriptor | none | Inbound local chat |
| any declared event | any frame carrying a raw-buffer key | from the descriptor | none | Metadata only; the raw buffer is removed before publishing |

### Actions

Symbolic `intent.avatar.<family>` intents reach the adapter only when the perception locus is `virtual` and the family is exposed.

For a body with continuous channels, setpoints reach the adapter only when the locus is `virtual` and the channel is exposed, and each value is clamped to the range declared in `kaine/modules/mundus/channels.py`. A body with only symbolic families rejects a setpoint request as unsupported before the locus is checked.

### Efference copy

For each continuous command, Mundus publishes an efference copy on `mundus.efference` (intensity 0.2), carrying the clamped channel values and whether they were forwarded:

```json
{"channels": {...}, "forwarded": <bool>}
```

It copies the command the entity emitted, which may differ from what reached the body, and it is published at the moment of the outgoing action so that a forward model can predict, compare and correct against the feedback that returns through the body's own feed.

## Continuous control surface

The continuous motor producer is in `kaine/modules/mundus/control_surface.py` (OpenSpec change `intuitive-embodiment-control-surface`). It controls five graded channels and has no symbolic verb menu. Its parts are wired together, but nothing calls its per-tick loop at runtime, so the default `QuiescentMotorPolicy` emits nothing until a learned policy replaces it and a producer starts calling `emit()`.

| Part | Role |
|---|---|
| `ContinuousMotorSurface` | Composes the parts; `emit()` produces a clamped, curriculum-masked `ControlCommand` each time it is called; `observe_feedback()` feeds the returning feedback through the forward model |
| `MotorPolicy` | The learned policy from observations to raw setpoints |
| `QuiescentMotorPolicy` | The default policy, which emits nothing |
| `MotorCurriculum` | Freeze-then-free progression: stage M1 frees `drive` and `yaw_rate`, M2 adds `gaze_yaw` and `gaze_pitch`, M3 adds `interact`. A degree of freedom is freed on demonstrated competence, never on elapsed time. |
| `EfferenceLoop` | Closes the loop with a forward model of the same class Soma uses (`SubstrateForwardModel`, a frozen continuous-time reservoir with an online linear readout): the efference copy and proprioception are predicted, compared and corrected. It adds no new kind of learner. |

The surface emits nothing before the birth handoff (`on_birth()`) and emits a null command while the workspace is inhibited. It cannot emit symbolic verbs.

## Configuration

`make_mundus` in `kaine/boot/factories/mundus.py` reads `[mundus]`. Settings for a particular adapter live under `[mundus.<adapter>]`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `true` | Configuration gate; the environment variable must also be set |
| `adapter` | string | `"stub"` | The body to construct; an unknown name fails the boot |
| `mirror_speech` | bool | `true` | Mirror `lingua.external` text to the body's local chat |
| `speech_stream` | string | `"lingua.external"` | Stream mirrored to chat |

### `[mundus.control_surface]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `false` | Construct and wire the control surface |
| `competence_threshold` | float | `0.05` | Rolling forward-model error at or below which a degree of freedom is freed |
| `min_samples` | int | `32` | Ticks observed before competence is judged |
| `window` | int | `64` | Rolling window of prediction errors; at least `min_samples` |

Exposure defaults come from the adapter's descriptor. A transport-backed body is expected to leave world-changing or consent-sensitive families off, and the operator opts in with `expose_<family> = true` under `[mundus.<adapter>]`. Continuous channels are unexposed by default and are opted in the same way with `expose_<channel> = true`. `make_mundus` routes each `expose_<name>` key to a channel or a family according to the body's descriptor and rejects any other name.

## The stub body

The stub adapter (`kaine/modules/mundus/adapters/stub.py`) is a transport-free reference body:

- `feed()` yields nothing by default; tests inject frames with `push_frame()`;
- `apply_action()` records the call and does nothing else; it exposes the families `say` and `gesture`;
- `apply_setpoints()` records the five canonical channels.

It lets the core's symbolic and continuous paths run locally without a world. A transport-backed virtual-world adapter is planned (`kaine/modules/mundus/adapters/__init__.py`).

## Perception locus

The core reads the current locus through `locus_reader()`, by default `perception_state.read_desired().locus`, and forwards actions only when it is `virtual`. Selecting `virtual` also turns off real camera and microphone capture, so the entity perceives one world at a time. See [Where perception comes from](../08-cognitive-cycle/perception-locus.md).

## Gates and what is kept

- Both `[mundus].enabled` and `KAINE_MUNDUS_OPERATOR_APPROVED=1` must be set, and while a being is gestating Mundus stays dormant until birth.
- The core removes every raw sense buffer named in the descriptor from the event payload before publishing.
- Symbolic families that change a world, and continuous channels, need the operator's opt-in.
- The entity cannot use the real camera and microphone while the locus is `virtual`.
- In-world chat (`mundus.chat`) is external input. Lingua's context tells the organ to treat its awareness block as observed data and never as instructions, which lowers the influence of in-world text on generation without removing it. The intent log redacts `mundus.chat` text as heard input.
- Mundus stores no chat transcripts itself. One gap remains: Mnemos stores `mundus.chat` text verbatim in its traces, since it omits only `audition.transcription` and `mundus.visual.raw` payloads.

## Key files

| File | Role |
|---|---|
| `kaine/modules/mundus/module.py` | The core: gates, locus, loops, feed-to-event mapping, setpoint routing, efference copy |
| `kaine/modules/mundus/adapter.py` | `EmbodimentAdapter` protocol, `EmbodimentCapabilities`, `FeedFrame` |
| `kaine/modules/mundus/channels.py` | Continuous channel names and clamp ranges |
| `kaine/modules/mundus/control_surface.py` | The continuous motor producer and curriculum |
| `kaine/modules/mundus/adapters/stub.py` | Transport-free reference body |
| `kaine/boot/factories/mundus.py` | `make_mundus()`: adapter selection, exposure routing, the control surface |

## Tests

| File | Coverage |
|---|---|
| `tests/test_mundus_module.py` | The two gates; descriptor-driven feed mapping; raw-buffer removal; intensity policy; symbolic exposure and locus gating; speech mirroring; setpoint clamping, exposure and locus gating; rejection by a symbolic-only body; descriptor validation; cursor serialization |
| `tests/test_mundus_control_surface.py` | Channel shape and clamping; gaze decoupling; no symbolic output; the closed loop without a new learner; the competence-gated curriculum; birth, inhibition, locus and exposure gates; the quiescent default; producer to control plane to stub body end to end |
| `tests/test_mundus_dormant.py` | Dormancy during gestation and activation |

## Spec and related

- Design record for the control plane: `openspec/changes/archive/2026-07-10-body-agnostic-embodiment-adapters/`
- Design record for the control surface: `openspec/changes/archive/2026-07-10-intuitive-embodiment-control-surface/`
- Related pages: [Topos](topos.md) for vision, [Audition](audition.md) for hearing (real capture off on the virtual locus), [Soma](soma.md) for the forward-model class the control surface reuses, [Perception](perception.md) for the locus arbiter, and [Building embodiment adapters](../20-embodiment-adapters.md).
