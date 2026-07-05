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

One adapter ships today: **OpenSim** (a transitional reference body — an avatar in
a local OpenSimulator grid via a forked Firestorm viewer driven over a LEAP shim).
A minimal transport-free **stub** adapter also ships, unselected, as the seam's
second reference body and the exerciser for the continuous-control path. The avatar
identity is the entity's avatar — a name the operator sets locally.

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

Feed kinds and their event/salience mapping come from the active adapter's
descriptor. The OpenSim adapter declares:

| Event type | Source frame | Default salience | Notes |
|---|---|---|---|
| `mundus.proprio` | `proprio` frame | 0.3 (0.8 if dying/falling) | Position, region, look_at, agent_id, display_name |
| `mundus.scene` | `scene` frame | 0.15 | Nearby object counts/types; symbolic surroundings |
| `mundus.entity` | `entity` frame | 0.2 (0.5 on arrival) | Nearby avatar ids, names, positions |
| `mundus.chat` | `chat` frame | 0.6 | Inbound local chat from other avatars |
| `mundus.visual.raw` | `frame` frame | 0.1 | Vision metadata only (w, h, encoding, seq); **raw frame buffer stripped** |
| `mundus.notice` | `notice` frame | 0.6 | Inbound offers/dialogs auto-handled per safety policy |
| `mundus.action.result` | `action_result` frame | 0.3 | Adapter op reply (ok / error) |

The salience bumps (proprio dying/falling → 0.8, entity arrival → 0.5) are the
core's salience policy, applied to any body.

### Actions (core → body)

`intent.avatar.<family>` events from `volition.out` are forwarded to the adapter's
symbolic sink only when:
1. The perception locus is `virtual` (checked via `locus_reader()`).
2. The action family is exposed (descriptor default, overridable in config).

Continuous setpoints are forwarded to the adapter's graded sink only when the locus
is `virtual`, the channel is exposed (default **off**), and the value is clamped to
the channel's declared range. A symbolic-only body rejects setpoints as unsupported.

---

## Configuration

The `[mundus]` config section is read by `make_mundus` in `boot.py`, which
constructs only the selected adapter from its nested `[mundus.<adapter>]` table.

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` (when constructed) | Config-side gate (must be `true` AND env var set) |
| `adapter` | `"opensim"` | Which body to construct; an unknown name fails closed at boot |
| `mirror_speech` | `true` | Mirror `lingua.external` text to the body's local chat |
| `speech_stream` | `"lingua.external"` | Source stream for speech mirroring |

OpenSim-adapter settings live under `[mundus.opensim]`:

| Key | Default | Description |
|---|---|---|
| `bridge_host` | `"127.0.0.1"` | Localhost only; the shim connects in |
| `bridge_port` | `7781` | TCP port for the shim connection |
| `expose_<family>` | per-action defaults | `expose_move = true`, `expose_teleport = false`, etc. |

Per-action-family exposure defaults (additional opt-in gate):

| Action | Default exposed |
|---|---|
| move, turn, say, sit_on, stand, animate, gesture | **true** |
| teleport, touch | **false** (world-mutating / script-triggering; operator opt-in) |

`[modules].mundus` must be `true` for the module to be instantiated.

---

## How it works — the OpenSim adapter

The OpenSim adapter (`kaine/modules/mundus/adapters/opensim.py`) is the current
transitional reference body. It owns a localhost TCP server that the LEAP shim
(running inside the forked Firestorm viewer) connects to, and speaks the
length-prefixed MessagePack wire protocol in `kaine/modules/mundus/bridge.py`.

### Deployment topology

```
 <world-host> (private-mesh node)
┌──────────────────────────────────┐
│  OpenSim standalone grid          │  dotnet 8, BSD-3, fully local
│  http://<world-host-mesh>:9000/   │  regions loaded from OAR archives
└──────────────┬───────────────────┘
               │ Second Life protocol (LLUDP + CAPS)
               │ over the encrypted private mesh
 <entity-host> (GPU workstation)
               ▼
┌──────────────────────────────────┐
│  Forked Firestorm viewer          │  -DOPENSIM:BOOL=ON
│  (renders the world)              │  + captureFrame LEAP op for vision
│  launched: --leap "<shim>"        │
└──────────────┬───────────────────┘
               │ LEAP: length-prefixed LLSD on stdin/stdout
               ▼
┌──────────────────────────────────┐
│  Mundus LEAP shim                 │  tools/mundus-leap/ (Python)
│  stateless relay + locomotion-    │  holds sustained locomotion state between
│  state holder                     │  cognitive ticks
└──────────────┬───────────────────┘
               │ length-prefixed MessagePack on TCP (loopback)
               ▼
┌──────────────────────────────────────────────────────────────┐
│  KAINE — OpenSim adapter behind the Mundus control plane      │
│  bus events  mundus.*  ──►  Redis workspace bus               │
│  intents     intent.avatar.*  ◄── volition.out                │
└──────────────────────────────────────────────────────────────┘
```

OpenSim runs on the **world host**; the rest runs on the **entity host** (the GPU
workstation). Only the Second Life protocol traverses the private mesh; the LEAP
bridge stays on loopback.

### Wire protocol

`bridge.py` defines length-prefixed MessagePack frames: a 4-byte big-endian length
header followed by that many bytes of MessagePack. Maximum frame size is 8 MiB.
Feed frames are keyed by `kind`; action frames carry `kind = "action"` plus
`action`, `reqid`, and params.

### Perception locus (physical XOR virtual)

The core reads the current desired locus via `locus_reader()` (a callable injected
at construction, defaulting to `perception_state.read_desired().locus`). Actions
are forwarded to the body **only when the locus is `virtual`**. Selecting `virtual`
also turns off the real camera/mic capture in the same transition (mutual exclusion
enforced by the perception-state machinery): the entity is present in one world at
a time.

### Inbound-world safety

All in-world text and scripted objects are treated as **data, not commands**. The
LEAP shim's default policy auto-declines inventory offers, teleport lures,
friendship offers, and group invitations, and default-denies script permission
requests. Every declined event is published as `mundus.notice` so the operator sees
it and Thymos/Eidolon register the solicitation as perception.

### Action vocabulary

| KAINE intent family | LEAP op | Default exposed |
|---|---|---|
| `move` | `LLAgent.startAutoPilot` (goal-based) | Yes |
| `turn` | `LLAgent.lookAt / resetAxes` | Yes |
| `say` | `LLChatBar.sendChat` | Yes |
| `sit_on` | `LLAgent.requestSit` | Yes |
| `stand` | `LLAgent.requestStand` | Yes |
| `animate` | `LLAgent.playAnimation` | Yes |
| `gesture` | `LLGesture.startGesture` | Yes |
| `teleport` | `LLAgent.requestTeleport` | **No** (opt-in) |
| `touch` | `LLAgent.requestTouch` | **No** (opt-in; can trigger scripts) |

No vocabulary for: economy actions (explicitly prohibited), rezzing objects,
editing terrain, inventory, group/friend management. The OpenSim adapter declares
no continuous channels — its locomotion is goal-based autopilot, not per-tick
graded control; continuous control arrives with a body that supports it.

---

## Key files

| File | Role |
|---|---|
| `kaine/modules/mundus/module.py` | `Mundus` — the body-agnostic core: gating, locus, intent/speech loops, feed→event mapping, continuous-setpoint routing |
| `kaine/modules/mundus/adapter.py` | `EmbodimentAdapter` protocol, `EmbodimentCapabilities` descriptor, `FeedFrame` |
| `kaine/modules/mundus/adapters/opensim.py` | OpenSim adapter (transitional reference body): TCP listener + LEAP bridge |
| `kaine/modules/mundus/adapters/stub.py` | Transport-free reference adapter; exercises the continuous-control path |
| `kaine/modules/mundus/bridge.py` | OpenSim wire protocol: `read_frame`, `write_frame`, `FEED_EVENT`, `ACTION_DEFAULT_EXPOSED` |
| `openspec/changes/body-agnostic-embodiment-adapters/` | The control-plane design of record |

---

## Safety / zero-persistence note

- **Two-layer gate:** both the config key and the env var must be set. Mundus logs
  which gate failed and returns from `initialize()` without opening any body if
  either is absent.
- **Zero raw-sense-data persistence:** the core strips every raw sense buffer the
  active adapter's descriptor names (for OpenSim, the `frame` feed's `data` field of
  raw RGB bytes) from the bus event payload before publishing. Only metadata rides
  the bus; frame bytes flow off the side channel to Topos in real-time and are
  discarded.
- **Per-family / per-channel exposure flags** gate world-mutating and
  script-triggering actions (`teleport`, `touch`) and every continuous channel to
  explicit operator opt-in.
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
| `tests/test_mundus_module.py` | Two-layer gate; feed mapping via descriptor; symbolic action exposure; speech mirroring; descriptor-drift guard; continuous-setpoint clamping / exposure / locus gating; symbolic-only rejection |

---

## Spec & related

- Design of record: `openspec/changes/body-agnostic-embodiment-adapters/`
  (supersedes `opensim-connector`, whose Mundus is now the OpenSim adapter, and
  folds `paracosm-connector`'s Kosmos into the adapter model).
- See also: Topos (vision input binding), Audition (hearing; muted in `virtual`
  locus), Volition (issues `intent.avatar.*` intents), Eidolon (embodiment
  self-image), Thymos (social-drive signal from nearby entities / chat), and
  `intuitive-embodiment-control-surface` (the continuous-control producer).
