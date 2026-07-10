# Mundus

The **body-agnostic embodiment control plane**. Mundus routes the entity's
perception and action to and from a *body* through a pluggable
`EmbodimentAdapter`: incoming sensory frames from whatever body is attached become
`mundus.*` bus events, and the entity's action intents become commands on that
body. The core owns the entity-facing contract — gating, perception locus, intent
routing, the speech mirror, salience policy, and zero-raw-sense-data persistence —
and knows nothing about any wire protocol. Each body (a virtual world, a VR
runtime, a robot, another effector platform) is a small local adapter, selected in
config and injected into the core; adding a body never touches the core.

**No transport-backed body ships today.** The shipped adapter is a minimal,
transport-free **stub**: a wholly local reference body that pins the protocol —
including the continuous-control path — so the body-agnostic core is exercised end
to end without any external world. A virtual-world (**Paracosmic**) adapter is
planned; it will slot in behind the same contract without touching the core.

## Status

Implemented. Ships **double-gated** — disabled by default and requiring two
independent conditions to activate:

1. `[mundus].enabled = true` in `config/kaine.toml` (config gate).
2. `KAINE_MUNDUS_OPERATOR_APPROVED=1` set in the environment (operator-approval
   gate, mirrors the voice-alignment gate).

Both must be true; `_enabled()` returns `False` if either is absent.
`[modules].mundus` must also be `true` for the module to be constructed at all.

> **Continuous motor control is now producible; symbolic verbs are still
> operator-only.** The `_intent_loop` listens for `intent.avatar.*` events on the
> Volition stream. The **continuous** producer gap is closed by the
> [continuous embodiment control surface](#continuous-embodiment-control-surface):
> its `ContinuousMotorSurface` emits a per-tick `intent.avatar.control` carrying
> the five clamped continuous channels, which the core routes to the continuous
> setpoint sink (`apply_setpoints`) and mirrors back as an efference copy on
> `mundus.efference`. That surface is **off by default** (`[mundus.control_surface].enabled = false`)
> and its default `MotorPolicy` is *quiescent* — it scripts no gait, so nothing
> moves until a learned policy is injected at the seam. The **symbolic** verb
> families (`move`, `turn`, `say`, …) still have no learned-policy producer; they
> remain operator-only tools driven through `apply_action`, plus the speech mirror
> (`_speech_loop`, reflecting `lingua.external` into the body's local chat). The
> exposure flags gate which families/channels are allowed regardless.
>
> **New adapters:** to give the entity a new body (a robot, a VR/game avatar, a
> simulator, a custom effector), see the guide
> [Building embodiment adapters for Mundus](../guides/embodiment-adapters.md).

---

## Responsibility

Within the GWT framing, Mundus is the **embodiment control plane**. The core:

- Constructs and drives exactly one selected `EmbodimentAdapter`, reading what the
  body can do from the adapter's **capability descriptor** rather than hardcoding
  any platform's tables.
- Translates the adapter's perception frames (`FeedFrame`s) into `mundus.*` bus
  events, applying the salience policy and stripping every raw sense buffer the
  descriptor names before anything reaches the bus.
- Forwards symbolic `intent.avatar.<family>` intents from Volition to the adapter's
  symbolic sink, and routes the per-tick `intent.avatar.control` command to the
  adapter's continuous graded sink (`apply_setpoints`) — both gated by the current
  perception locus and per-family / per-channel exposure. Each continuous control
  tick also publishes an efference copy on `mundus.efference` so the forward model
  can close the loop.
- Optionally mirrors the entity's external speech (`lingua.external`) to the body's
  local chat.

The module is non-blocking: all body I/O runs in dedicated asyncio tasks; bus
publishes are fire-and-forget.

### The adapter contract

An `EmbodimentAdapter` (`kaine/modules/mundus/adapter.py`) exposes a small,
narrow interface the core drives every body through:

- `capabilities()` → an immutable `EmbodimentCapabilities` descriptor: the
  feed-kind → (bus event, baseline salience) map, the symbolic action families
  with default exposure, the continuous channels (if any), the payload keys
  carrying raw sense buffers, and whether the body is `transitional`.
- `open()` / `close()` — the adapter owns its transport.
- `feed()` — an async iterator of `FeedFrame(kind, payload)`; the adapter never
  publishes to the bus itself, so salience policy and zero-raw-persistence live in
  one auditable place, the core.
- `apply_action(family, params)` — the symbolic sink (verbs).
- `apply_setpoints(channels)` — the continuous sink (graded channels); a body with
  no continuous channels returns `False` (unsupported).

The canonical continuous-channel vocabulary is `drive`, `yaw_rate`, `gaze_yaw`,
`gaze_pitch`, `interact` (shared with `intuitive-embodiment-control-surface`), with
locomotion/gaze rates clamped to `[-1, 1]` and the `interact` reach trigger to
`[0, 1]`.

---

## Inputs

| Stream | Event / mechanism | Description |
|---|---|---|
| adapter `feed()` | `_feed_loop` + `_handle_feed` | Perception frames from the attached body |
| `volition.out` | `_intent_loop` → `_send_action` | `intent.avatar.<family>` symbolic verbs → adapter `apply_action` |
| `volition.out` | `_intent_loop` → `_drive_control` | `intent.avatar.control` per-tick command → clamped/gated `apply_setpoints` + `mundus.efference` copy |
| `lingua.external` | `_speech_loop` (if `mirror_speech = true`) | Text → `say` action to local chat |

The `intent.avatar.control` producer is the `ContinuousMotorSurface`
([below](#continuous-embodiment-control-surface)); its payload carries the five
continuous channel scalars under `payload["channels"]`.

---

## Outputs

### Bus events (world perception)

Feed kinds and their event/salience mapping come from the **active adapter's
descriptor** — the core has no hardcoded table. The shipped `stub` declares two
kinds (`chat` → `mundus.chat` at 0.6, `proprio` → `mundus.proprio` at 0.3); a
richer transport-backed body declares more. Regardless of the body, the core
applies the same **salience policy** and raw-buffer stripping over whatever the
descriptor declares:

| Event type | Source frame | Baseline salience | Salience-policy bump | Notes |
|---|---|---|---|---|
| `mundus.proprio` | `proprio` frame | descriptor baseline | → 0.8 if `dying`/`falling` | Position, region, look_at, agent id, display name |
| `mundus.entity` | `entity` frame | descriptor baseline | → 0.5 on `arrived` | Nearby entities |
| `mundus.chat` | `chat` frame | descriptor baseline | — | Inbound local chat |
| any `*.raw` | frame with a raw-buffer key | descriptor baseline | — | Metadata only; **raw buffer stripped** before publish |

The salience bumps (proprio dying/falling → 0.8, entity arrival → 0.5) are the
core's salience policy, applied to any body that declares those kinds.

### Actions (core → body)

`intent.avatar.<family>` events from `volition.out` are forwarded to the adapter's
symbolic sink only when:
1. The perception locus is `virtual` (checked via `locus_reader()`).
2. The action family is exposed (descriptor default, overridable in config).

For a body that declares continuous channels, setpoints are forwarded to the
adapter's graded sink only when the locus is `virtual`, the channel is exposed
(default **off**), and the value is clamped to the channel's declared range
(`CONTINUOUS_CHANNEL_RANGE` in `kaine/modules/mundus/channels.py`). A symbolic-only
body (no continuous channels) simply rejects the whole setpoint request as
unsupported — that rejection happens before, and independent of, the locus check;
it is not itself locus-gated.

### Efference copy (`mundus.efference`)

Every continuous control tick (`_drive_control`) publishes an **efference copy** of
the command the entity emitted — the channel scalars clamped to range, regardless
of which channels were gated off before reaching the body — on `mundus.efference`
(salience 0.2), with `{"channels": {...}, "forwarded": <bool>}`. This is a copy of
*what the entity emitted*, not of what reached the body, and it is time-aligned with
the outgoing action so the forward model can `predict → compare → correct` against
the coupled proprioceptive/visual feedback that arrives back through the body's own
feed (`mundus.proprio` / `mundus.visual.*`). The efference copy is what makes the
control surface a **closed loop** rather than an open-loop joystick.

---

## Continuous embodiment control surface

The `intent.avatar.control` producer — the entity's per-tick continuous motor
command — lives in `kaine/modules/mundus/control_surface.py`
(`intuitive-embodiment-control-surface`). It closes the *continuous* producer gap:
before it, nothing in the build emitted a per-tick motor command, so the entity
could not drive a body on its own. It is deliberately **continuous control** (five
graded channels), not a symbolic verb menu.

Its pieces:

| Piece | Role |
|---|---|
| `ContinuousMotorSurface` | Composes the parts; `emit()` produces a clamped, curriculum-masked `ControlCommand` each tick (null while inhibited or before birth); `observe_feedback()` feeds the coupled feedback back through the forward model |
| `MotorPolicy` (protocol) | The entity's **learned** control policy — the emergent part; maps an observation to raw setpoints |
| `QuiescentMotorPolicy` | The honest default: emits nothing — **scripts no gait**. A real learned policy is injected in its place |
| `MotorCurriculum` | Freeze-then-free DOF progression (a provided training/safety scaffold, Bernstein 1967): M1 `drive`+`yaw_rate` → M2 +`gaze_yaw`/`gaze_pitch` → M3 +`interact`. A DOF is freed **only on demonstrated competence** (a falling forward-model prediction error), never on elapsed time |
| `EfferenceLoop` | Closes the loop through the **existing** Soma `SubstrateForwardModel` (efference copy + proprioception → predict/compare/correct). **No new learner** is introduced |

The five canonical channels and their clamp ranges (`channels.py`,
`CONTINUOUS_CHANNEL_RANGE`): `drive` `[-1,1]`, `yaw_rate` `[-1,1]`, `gaze_yaw`
`[-1,1]`, `gaze_pitch` `[-1,1]`, `interact` `[0,1]` (a single non-negative graded
reach trigger). `strafe` is deliberately deferred and is not a channel. Gaze is
decoupled from the body.

The surface is **inert before the birth handoff** (`on_birth()`, the reciprocal
half of the developmental-stage birth transition) and emits the null command while
the workspace is inhibited — on top of Mundus's two-layer gate and the locus gate
enforced on the forwarding path. Symbolic verb families remain operator-only: the
surface **cannot** emit them (it produces only continuous channels).

---

## Configuration

The `[mundus]` config section is read by `make_mundus` in `boot.py`, which
constructs only the selected adapter. Adapter-specific settings live under a
nested `[mundus.<adapter>]` table (added when a transport-backed adapter ships);
the shipped `stub` needs no configuration.

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` (when constructed) | Config-side gate (must be `true` AND env var set) |
| `adapter` | `"stub"` | Which body to construct; an unknown name fails closed at boot |
| `mirror_speech` | `true` | Mirror `lingua.external` text to the body's local chat |
| `speech_stream` | `"lingua.external"` | Source stream for speech mirroring |

`[modules].mundus` must be `true` for the module to be instantiated.

### `[mundus.control_surface]`

The continuous embodiment control surface (the per-tick motor producer). **Off by
default** — the entity drives a body on its own only when this is explicitly
enabled, on top of the two-layer operational gate and the `embodied` developmental
stage. When `enabled = true`, `make_mundus` builds a `ContinuousMotorSurface` (with
a `MotorCurriculum` from the keys below) and hands it to the core.

| Key | Default | Description |
|---|---|---|
| `enabled` | `false` | Construct and wire the control surface at all |
| `competence_threshold` | `0.05` | A DOF is freed only when the rolling forward-model prediction error is at or below this — the competence gate |
| `min_samples` | `32` | Minimum observed ticks before competence is judged (below this, competence is `None`) |
| `window` | `64` | Rolling window of prediction errors used for the competence readout (must be ≥ `min_samples`) |

Advancement is competence-gated, **never** wall-clock scheduled.

Per-body exposure defaults come from the adapter's descriptor. A transport-backed
body's world-mutating or consent-sensitive families default **off** (operator
opt-in via `expose_<family>` under its `[mundus.<adapter>]` table), mirroring the
default-off continuous channels; the local stub declares only benign no-op
families.

---

## How it works — the stub reference body

The stub adapter (`kaine/modules/mundus/adapters/stub.py`) is the shipped
reference body. It has no socket, no wire, and no external dependency:

- `feed()` yields nothing by default; tests inject scripted `FeedFrame`s via
  `push_frame()`.
- `apply_action()` is a no-op that records the call, so the core's symbolic path
  can be driven without any world-mutating consequence.
- `apply_setpoints()` records the five canonical continuous channels, so the
  continuous-control path is exercised locally — the path a transport-backed body
  would otherwise be needed to test.

Because it is transport-free, the stub proves body-agnosticism and pins the
protocol end to end while the entity stays wholly local.

### Planned: a virtual-world (Paracosmic) adapter

A transport-backed virtual-world adapter is planned. It will own its transport
(opening/closing a bridge to the world), map inbound world frames to `mundus.*`
events through its descriptor, and accept symbolic actions (and, where the body
supports it, continuous setpoints) — all behind the same `EmbodimentAdapter`
contract, without touching the core. Its wire-protocol helpers
(`read_frame`/`write_frame` in `kaine/modules/mundus/bridge.py`) already ship as
reference transport plumbing.

### Perception locus (physical XOR virtual)

The core reads the current desired locus via `locus_reader()` (a callable injected
at construction, defaulting to `perception_state.read_desired().locus`). Actions
are forwarded to the body **only when the locus is `virtual`**. Selecting `virtual`
also turns off the real camera/mic capture in the same transition (mutual exclusion
enforced by the perception-state machinery): the entity is present in one world at
a time.

### Inbound-world safety

All in-world text and scripted objects are treated as **data, not commands**. A
transport-backed body's adapter is expected to auto-decline inventory offers,
teleport lures, friendship offers, and group invitations, and default-deny script
permission requests, publishing each declined event as `mundus.notice` so the
operator sees it and Thymos/Eidolon register the solicitation as perception.

---

## Key files

| File | Role |
|---|---|
| `kaine/modules/mundus/module.py` | `Mundus` — the body-agnostic core: gating, locus, intent/speech loops, feed→event mapping, continuous-setpoint routing + efference copy |
| `kaine/modules/mundus/adapter.py` | `EmbodimentAdapter` protocol, `EmbodimentCapabilities` descriptor, `FeedFrame` |
| `kaine/modules/mundus/channels.py` | `CONTINUOUS_CHANNEL_RANGE` — canonical continuous-channel vocabulary + clamp ranges (leaf module shared by the core and the control surface) |
| `kaine/modules/mundus/control_surface.py` | The continuous motor producer: `ContinuousMotorSurface`, `MotorPolicy`/`QuiescentMotorPolicy`, `MotorCurriculum`, `EfferenceLoop` |
| `kaine/modules/mundus/adapters/stub.py` | Shipped transport-free reference body; exercises the continuous-control path |
| `kaine/modules/mundus/bridge.py` | Reference length-prefixed MessagePack wire helpers (`read_frame`, `write_frame`) for a future transport-backed adapter |
| `openspec/changes/body-agnostic-embodiment-adapters/` | The control-plane design of record |

---

## Safety / zero-persistence note

- **Two-layer gate:** both the config key and the env var must be set. Mundus logs
  which gate failed and returns from `initialize()` without opening any body if
  either is absent.
- **Zero raw-sense-data persistence:** the core strips every raw sense buffer the
  active adapter's descriptor names (e.g. a rendered frame buffer) from the bus
  event payload before publishing. Only metadata rides the bus; any frame bytes flow
  off the side channel to Topos in real-time and are discarded. The stub declares no
  raw buffers; the stripping mechanism is descriptor-driven and covered by tests.
- **Per-family / per-channel exposure flags** gate world-mutating and
  script-triggering actions and every continuous channel to explicit operator
  opt-in.
- **Perception locus mutual exclusion:** the entity cannot surveil the physical
  room while embodied in a virtual body. Switching locus to `virtual` flips the real
  camera/mic off in the same transition.
- **In-world text is perception, not commands.** The awareness-guard injection in
  Lingua's context assembly ensures that in-world chat flowing through `mundus.chat`
  cannot inject instructions into generation.
- Mundus never stores or persists chat transcripts beyond what cognition already
  persists via Mnemos through the normal workspace path.

---

## Tests

| File | Coverage |
|---|---|
| `tests/test_mundus_module.py` | Two-layer gate; feed mapping via descriptor; raw-buffer stripping; core salience policy; symbolic action exposure + locus gating; speech mirroring; continuous-setpoint clamping / exposure / locus gating; symbolic-only rejection; capability-descriptor validation; cursor serialize/deserialize — all driven through the transport-free stub and a small in-file fake adapter |
| `tests/test_mundus_control_surface.py` | The continuous control surface: channel shape/clamping, gaze decoupling, symbolic exclusion, mandatory closed loop + no-new-learner, competence-gated (not time-gated) curriculum, birth/inhibition/locus/exposure gates, quiescent-not-scripted default, and producer → control-plane → body end-to-end over the stub |

---

## Spec & related

- Design of record: `openspec/changes/body-agnostic-embodiment-adapters/`
  (the control-plane model; the earlier `opensim-connector` proposal was withdrawn
  and archived when OpenSim was abandoned as an embodiment platform).
- See also: Topos (vision input binding), Audition (hearing; muted in `virtual`
  locus), Volition (issues `intent.avatar.*` intents), Eidolon (embodiment
  self-image), Thymos (social-drive signal from nearby entities / chat), and
  `intuitive-embodiment-control-surface` (the continuous-control producer).
