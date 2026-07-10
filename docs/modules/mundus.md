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

> **Motor control not yet reachable by the entity:** the `_intent_loop` listens
> for `intent.avatar.*` events on the Volition stream, and the continuous-setpoint
> sink listens for graded channel commands. Volition currently emits only
> `intent.speak`, `intent.think`, and `intent.act`; no module produces an
> `intent.avatar.*` event or drives the continuous channels. So the symbolic motor
> families and the continuous channels are unreachable at runtime — only speech
> mirroring (`_speech_loop`, reflecting `lingua.external` into the body's local
> chat) is live. The exposure flags still gate which families/channels *would* be
> allowed once a producer exists (the continuous producer is the
> `intuitive-embodiment-control-surface` change).

---

## Responsibility

Within the GWT framing, Mundus is the **embodiment control plane**. The core:

- Constructs and drives exactly one selected `EmbodimentAdapter`, reading what the
  body can do from the adapter's **capability descriptor** rather than hardcoding
  any platform's tables.
- Translates the adapter's perception frames (`FeedFrame`s) into `mundus.*` bus
  events, applying the salience policy and stripping every raw sense buffer the
  descriptor names before anything reaches the bus.
- Forwards `intent.avatar.*` intents from Volition to the adapter's symbolic sink,
  and (future) continuous setpoints to its graded sink — both gated by the current
  perception locus and per-family / per-channel exposure.
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
| `volition.out` | `_intent_loop` | `intent.avatar.*` events → adapter symbolic sink |
| (future producer) | `apply_setpoints` | Continuous graded channel commands → adapter continuous sink |
| `lingua.external` | `_speech_loop` (if `mirror_speech = true`) | Text → `say` action to local chat |

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
(default **off**), and the value is clamped to the channel's declared range. A
symbolic-only body (no continuous channels) simply rejects the whole setpoint
request as unsupported — that rejection happens before, and independent of,
the locus check; it is not itself locus-gated.

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
| `kaine/modules/mundus/module.py` | `Mundus` — the body-agnostic core: gating, locus, intent/speech loops, feed→event mapping, continuous-setpoint routing |
| `kaine/modules/mundus/adapter.py` | `EmbodimentAdapter` protocol, `EmbodimentCapabilities` descriptor, `FeedFrame` |
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

---

## Spec & related

- Design of record: `openspec/changes/body-agnostic-embodiment-adapters/`
  (the control-plane model; the earlier `opensim-connector` proposal was withdrawn
  and archived when OpenSim was abandoned as an embodiment platform).
- See also: Topos (vision input binding), Audition (hearing; muted in `virtual`
  locus), Volition (issues `intent.avatar.*` intents), Eidolon (embodiment
  self-image), Thymos (social-drive signal from nearby entities / chat), and
  `intuitive-embodiment-control-surface` (the continuous-control producer).
