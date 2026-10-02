# Mundus

Mundus is KAINE's body-agnostic embodiment control plane. It routes perception from a body into the workspace as `mundus.*` bus events and routes the entity's action intents back to the body. Read this page if you are enabling a body, building an adapter, or auditing the embodiment gates.

## Status and gates

Mundus is disabled by default. It is off in the shipped `config/kaine.toml` and in the base-thesis `thesis_test` profile. Three conditions must all be true before Mundus is constructed and activated:

1. `[modules].mundus = true` in `config/kaine.toml` — the module is instantiated at all.
2. `[mundus].enabled = true` in `config/kaine.toml` — the config gate.
3. `KAINE_MUNDUS_OPERATOR_APPROVED=1` in the environment — the operator-approval gate, matching the voice-alignment gate pattern.

`_enabled()` returns false unless both the config key and the environment variable are set. If a gate is missing, Mundus logs which one failed and `initialize()` returns without opening the body.

Mundus is not dormant by default. `probe_available()` checks whether activation is possible, `activate()` starts the feed, intent, and speech loops, and `set_dormant()` stops them again. Mundus is held dormant only when staging/gestation is enabled and the entity is still gestating, via `GESTATION_DORMANT_EFFECTORS`; in that case the body does not open and the loops do not run until gestation completes. Otherwise `initialize()` opens the body as soon as the gates pass.

No transport-backed adapter is implemented yet. The included adapter is a transport-free stub that pins the protocol locally. To build a new body adapter, see [Building embodiment adapters for Mundus](../20-embodiment-adapters.md).

Continuous motor control is producible but not enabled by default, and nothing drives the per-tick loop at runtime. The continuous control surface is off (`[mundus.control_surface].enabled = false`), its default policy is quiescent, and continuous channels are off by default. Symbolic verb families such as `move`, `turn`, and `say` have no learned-policy producer; they remain operator-only tools.

## Responsibility

The Mundus core constructs and drives exactly one selected `EmbodimentAdapter`. It reads the adapter's capability descriptor rather than hardcoding any platform's tables. It:

- Translates feed frames from `adapter.feed()` into `mundus.*` bus events, applying the salience policy and stripping raw sense buffers named in the descriptor before anything reaches the bus.
- Forwards symbolic `intent.avatar.<family>` intents from the Volition stream to the adapter's symbolic sink, gated by the perception locus and per-family exposure.
- Routes the `intent.avatar.control` command to the adapter's continuous graded sink, gated by the locus and per-channel exposure, and publishes an efference copy on `mundus.efference`.
- Mirrors the entity's external speech (`lingua.external`) to the body's local chat when `mirror_speech` is true.

All body I/O runs in dedicated asyncio tasks and bus publishes are fire-and-forget.

## The adapter contract

An `EmbodimentAdapter` (`kaine/modules/mundus/adapter.py`) exposes a narrow interface:

| Method / property | Purpose |
|---|---|
| `capabilities()` | Returns an immutable `EmbodimentCapabilities` descriptor: feed-kind → (bus event, baseline salience), symbolic action families with default exposure, continuous channels, raw-buffer payload keys, and whether the body is `transitional`. |
| `open()` / `close()` | The adapter owns its transport. |
| `feed()` | Async iterator of `FeedFrame(kind, payload)`; the adapter never publishes to the bus itself. |
| `apply_action(family, params)` | Symbolic sink for verbs. |
| `apply_setpoints(channels)` | Continuous graded sink; a body with no continuous channels returns `False`. |

The canonical continuous channels are `drive`, `yaw_rate`, `gaze_yaw`, `gaze_pitch`, and `interact`, with locomotion/gaze rates clamped to `[-1, 1]` and `interact` clamped to `[0, 1]`.

## Inputs

| Stream | Event / mechanism | Description |
|---|---|---|
| `adapter.feed()` | `_feed_loop` / `_handle_feed` | Perception frames from the attached body |
| `volition.out` | `_intent_loop` → `_send_action` | `intent.avatar.<family>` symbolic verbs → `apply_action` |
| `volition.out` | `_intent_loop` → `_drive_control` | `intent.avatar.control` command → clamped/gated `apply_setpoints` + `mundus.efference` copy |
| `lingua.external` | `_speech_loop` (if `mirror_speech = true`) | Text → `say` action to local chat |

## Outputs

### Bus events

Feed kinds and their event/salience mapping come from the active adapter's descriptor. The included stub declares `chat` → `mundus.chat` at 0.6 and `proprio` → `mundus.proprio` at 0.3. The core applies the same salience policy and raw-buffer stripping to whatever the descriptor declares:

| Event | Source frame | Baseline salience | Policy bump | Notes |
|---|---|---|---|---|
| `mundus.proprio` | `proprio` | descriptor baseline | → 0.8 if `dying` or `falling` | No shipped payload schema |
| `mundus.chat` | `chat` | descriptor baseline | — | Inbound local chat |
| `*.raw` | any frame with a raw-buffer key | descriptor baseline | — | Metadata only; raw buffer stripped before publish |

### Actions

Symbolic `intent.avatar.<family>` events are forwarded to the adapter's symbolic sink only when the perception locus is `virtual` and the family is exposed.

For bodies with continuous channels, setpoints are forwarded only when the locus is `virtual`, the channel is exposed, and the value is clamped to the channel's declared range in `kaine/modules/mundus/channels.py`. A symbolic-only body rejects the whole setpoint request as unsupported before the locus check.

### Efference copy

When a continuous control command is produced, Mundus publishes an efference copy on `mundus.efference` (salience 0.2). The payload carries the clamped channel scalars and a `forwarded` boolean:

```json
{"channels": {...}, "forwarded": <bool>}
```

This is a copy of what the entity emitted, not of what reached the body. It is time-aligned with the outgoing action so the forward model can predict, compare, and correct against the feedback that returns through the body's own feed.

## Continuous embodiment control surface

The continuous motor producer lives in `kaine/modules/mundus/control_surface.py` (`intuitive-embodiment-control-surface`). It is continuous control (five graded channels), not a symbolic verb menu. The pieces are wired together, but nothing drives the per-tick loop at runtime, so the default `QuiescentMotorPolicy` emits nothing and nothing moves until a learned policy replaces it and a producer starts calling `emit()`.

| Piece | Role |
|---|---|
| `ContinuousMotorSurface` | Composes the parts; `emit()` produces a clamped, curriculum-masked `ControlCommand` each tick it is called; `observe_feedback()` feeds coupled feedback back through the forward model. |
| `MotorPolicy` | The learned policy that maps observations to raw setpoints. |
| `QuiescentMotorPolicy` | The default policy: emits nothing. |
| `MotorCurriculum` | Freeze-then-free progression: M1 `drive` + `yaw_rate`; M2 adds `gaze_yaw` / `gaze_pitch`; M3 adds `interact`. A degree of freedom is freed only on demonstrated competence, never on elapsed time. |
| `EfferenceLoop` | Closes the loop through Soma's `SubstrateForwardModel`: efference copy + proprioception → predict/compare/correct. No new learner is added. |

The surface is inert before the birth handoff (`on_birth()`) and emits a null command while the workspace is inhibited. Symbolic verb families remain operator-only: the surface cannot emit them.

## Configuration

The `[mundus]` section is read by `make_mundus` in `kaine/boot.py`. Adapter-specific settings live under `[mundus.<adapter>]`.

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` (when constructed) | Config-side gate; both this and the env var must be true |
| `adapter` | `"stub"` | Which body to construct; an unknown name fails closed at boot |
| `mirror_speech` | `true` | Mirror `lingua.external` text to the body's local chat |
| `speech_stream` | `"lingua.external"` | Source stream for speech mirroring |

### `[mundus.control_surface]`

| Key | Default | Description |
|---|---|---|
| `enabled` | `false` | Construct and wire the control surface |
| `competence_threshold` | `0.05` | Rolling forward-model prediction-error threshold for freeing a degree of freedom |
| `min_samples` | `32` | Minimum observed ticks before competence is judged |
| `window` | `64` | Rolling window of prediction errors; must be at least `min_samples` |

Per-body exposure defaults come from the adapter's descriptor. A transport-backed body defaults world-mutating or consent-sensitive families to off; the operator opts in with `expose_<family>` under `[mundus.<adapter>]`. Continuous channels are also off by default and are opted in with `expose_<channel>`. `make_mundus` routes each `expose_<name>` key by the body's declared channels and families, and refuses any other name.

## The stub reference body

The included stub adapter (`kaine/modules/mundus/adapters/stub.py`) is a transport-free reference body:

- `feed()` yields nothing by default; tests inject scripted frames via `push_frame()`.
- `apply_action()` is a no-op that records the call.
- `apply_setpoints()` records the five canonical continuous channels.

This lets the core's symbolic and continuous paths run locally without a world.

### Planned virtual-world adapter

A transport-backed Paracosmic adapter is planned (see `kaine/modules/mundus/adapters/__init__.py`); the old Kosmos connector design was archived as superseded. Until it ships, the only included adapter is the transport-free `stub`.

### Perception locus

The core reads the current desired locus via `locus_reader()` (defaulting to `perception_state.read_desired().locus`). Actions are forwarded only when the locus is `virtual`. Selecting `virtual` also turns off the real camera and microphone capture in the same transition; the entity is present in one world at a time. See [Where perception comes from](../08-cognitive-cycle/perception-locus.md).

### Inbound-world safety

All in-world text and scripted objects are treated as data, not commands. A transport-backed adapter is expected to auto-decline inventory offers, teleport lures, friendship offers, group invitations, and script permission requests, publishing each declined event as `mundus.notice` so the operator sees it and Thymos/Eidolon register the solicitation as perception.

## Key files

| File | Role |
|---|---|
| `kaine/modules/mundus/module.py` | The body-agnostic core: gating, locus, loops, feed→event mapping, setpoint routing, efference copy |
| `kaine/modules/mundus/adapter.py` | `EmbodimentAdapter` protocol, `EmbodimentCapabilities` descriptor, `FeedFrame` |
| `kaine/modules/mundus/channels.py` | Canonical continuous-channel vocabulary and clamp ranges |
| `kaine/modules/mundus/control_surface.py` | The continuous motor producer and curriculum |
| `kaine/modules/mundus/adapters/stub.py` | Transport-free reference body |
| `openspec/changes/archive/2026-07-10-body-agnostic-embodiment-adapters/` | Design record for the control plane |
| `openspec/changes/archive/2026-07-10-intuitive-embodiment-control-surface/` | Design record for the continuous control surface |

## Safety and persistence

- **Two-layer gate:** both `[mundus].enabled` and `KAINE_MUNDUS_OPERATOR_APPROVED=1` must be set. The module logs the missing gate and returns from `initialize()` without opening the body.
- **Gestation dormancy:** if staging/gestation is enabled, `GESTATION_DORMANT_EFFECTORS` keeps Mundus dormant until gestation completes. Otherwise `initialize()` opens the body as soon as the gates pass.
- **Zero raw-sense-data persistence:** the core strips every raw sense buffer named in the adapter descriptor from the bus event payload before publishing. Only metadata rides the bus; frame bytes flow off the side channel to Topos in real time and are discarded.
- **Per-family exposure:** symbolic world-mutating or consent-sensitive families are gated to operator opt-in. Per-channel continuous exposure is intended to gate continuous channels, but the wiring gap means they cannot be enabled from configuration and remain off.
- **Perception locus mutual exclusion:** the entity cannot use the physical camera and microphone while the locus is `virtual`.
- **In-world text is perception, not commands:** the awareness-guard injection in Lingua's context assembly tags in-world chat on `mundus.chat` as data, not instructions. That reduces its influence on generation, but it does not eliminate it.
- Mundus does not store or persist chat transcripts beyond what cognition already persists through Mnemos on the normal workspace path.

## Tests

| File | Coverage |
|---|---|
| `tests/test_mundus_module.py` | Two-layer gate; descriptor-driven feed mapping; raw-buffer stripping; salience policy; symbolic action exposure and locus gating; speech mirroring; continuous-setpoint clamping, exposure, and locus gating; symbolic-only rejection; descriptor validation; cursor serialization |
| `tests/test_mundus_control_surface.py` | Channel shape and clamping; gaze decoupling; symbolic exclusion; closed loop without a new learner; competence-gated curriculum; birth/inhibition/locus/exposure gates; quiescent default; end-to-end producer → control plane → body over the stub |

## Spec and related

- Design record for the control plane: `openspec/changes/archive/2026-07-10-body-agnostic-embodiment-adapters/`
- Design record for the continuous control surface: `openspec/changes/archive/2026-07-10-intuitive-embodiment-control-surface/`
- Related pages: [Topos](../09-modules/topos.md) for vision input binding, [Audition](../09-modules/audition.md) for hearing (muted in `virtual` locus), [Eidolon](../09-modules/eidolon.md) for embodiment self-image, [Thymos](../09-modules/thymos.md) for social-drive signals from nearby entities and chat, [Where perception comes from](../08-cognitive-cycle/perception-locus.md), and the [continuous embodiment control surface](#continuous-embodiment-control-surface) section on this page.
