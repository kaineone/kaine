# Building embodiment adapters for Mundus

This guide teaches you how to give a KAINE entity a **new body** — a physical
robot, a VR or game avatar, a simulator, or a custom effector — by writing a small
local adapter. You will not touch the cognitive core, the bus, or the workspace;
you implement one narrow interface and declare what your body can do.

Read [`modules/mundus.md`](../modules/mundus.md) first for the control-plane
overview. This guide is the hands-on companion: it walks the `EmbodimentAdapter`
contract from the real code, then builds a minimal skeleton adapter you can copy.

---

## The big picture

**Mundus is a body-agnostic control plane.** It routes the entity's perception and
action to and from *a body*, and owns the entity-facing contract — gating,
perceptual locus, intent routing, the speech mirror, salience policy, and the
zero-raw-sense-data guarantee. The core knows **no** wire protocol, transport, or
platform vocabulary.

A **body** is a small, local **adapter** that:

1. implements one narrow interface — the `EmbodimentAdapter` protocol
   (`kaine/modules/mundus/adapter.py`); and
2. declares a **capability descriptor** (`EmbodimentCapabilities`) that tells the
   core, at runtime, what the body can perceive and do.

The core reads the descriptor instead of hardcoding any platform's tables, so
**adding a body never touches the core.** You add one file under
`kaine/modules/mundus/adapters/`, register it in one place at boot, and select it
in config.

```
 entity ──intent.avatar.*──▶  Mundus core  ──apply_action / apply_setpoints──▶  YOUR ADAPTER ──▶ body
 entity ◀──mundus.* events──  Mundus core  ◀──────── feed() yields FeedFrame ───  YOUR ADAPTER ◀── body
```

The shipped reference body is the transport-free
[`stub`](../modules/mundus.md#how-it-works--the-stub-reference-body)
(`adapters/stub.py`): it pins the whole protocol — including the continuous-control
path — with no socket and no external dependency. Use it as your template and your
conformance-test baseline. A virtual-world (Paracosmic) adapter is planned behind
the same contract; no transport-backed body ships today.

---

## The `EmbodimentAdapter` protocol

`kaine/modules/mundus/adapter.py` defines the protocol the core drives every body
through. It is a `runtime_checkable` `Protocol`, so your adapter needs no base
class — it just needs these six members:

```python
class EmbodimentAdapter(Protocol):
    def capabilities(self) -> EmbodimentCapabilities: ...
    async def open(self) -> None: ...          # bind/connect/spawn the transport
    async def close(self) -> None: ...          # tear it down; idempotent
    def feed(self) -> AsyncIterator[FeedFrame]: ...          # perception: body → core
    async def apply_action(self, family: str, params: dict) -> bool: ...   # symbolic sink
    async def apply_setpoints(self, channels: dict[str, float]) -> bool: ...  # continuous sink
```

| Method | Direction | What it does |
|---|---|---|
| `capabilities()` | — | Return the immutable capability descriptor (below). Called on construction and on every feed/action, so keep it cheap and constant. |
| `open()` | — | Bind the socket / connect / spawn the transport. Called once when Mundus initializes (only if the two-layer gate passes). |
| `close()` | — | Tear the transport down. Must be idempotent. |
| `feed()` | body → core | Async-iterate `FeedFrame(kind, payload)` values until the body disconnects. The core pumps this in its own task and maps each frame to a bus event. **Never publish to the bus yourself.** |
| `apply_action(family, params)` | core → body | The **symbolic** sink: perform a whole-action verb (`move`, `say`, `gesture`, …). Return `True` if the command was sent. |
| `apply_setpoints(channels)` | core → body | The **continuous** sink: drive graded per-tick channels. Return `True` if sent; a body with no continuous channels returns `False` (unsupported). |

### Which methods to implement

- **Symbolic-only body** (a body driven by discrete verbs — say a chat avatar or a
  gripper with `open`/`close` commands): implement `apply_action`, and make
  `apply_setpoints` return `False`. Declare `continuous_channels=()`.
- **Continuous-capable body** (a robot base you steer with velocities, an avatar you
  drive with a joystick-like signal): implement `apply_setpoints` over the canonical
  channels, and declare them in `continuous_channels`. You may also implement
  `apply_action` for whole-action verbs the same body supports.

Both sinks may coexist on one body. The core decides which to call based on the
intent it receives (see [Action](#action-entity--body)).

---

## The `EmbodimentCapabilities` descriptor

`EmbodimentCapabilities` (a frozen dataclass) is how your body tells the core what
it can do. It is validated in `__post_init__`, so a malformed descriptor fails
loudly at construction.

```python
@dataclass(frozen=True)
class EmbodimentCapabilities:
    name: str
    transitional: bool
    feed_events: Mapping[str, Tuple[str, float]]
    action_families: Mapping[str, bool]
    continuous_channels: Tuple[str, ...] = ()
    raw_buffer_keys: Tuple[str, ...] = ()
```

| Field | Meaning | Example |
|---|---|---|
| `name` | Adapter identity (non-empty). Matches the `[mundus].adapter` value that selects it. | `"robot"` |
| `transitional` | `True` marks a body expected to be retired — a reference/conformance body rather than a long-lived one. | `False` for a real body |
| `feed_events` | feed `kind` → `(bus event type, baseline salience in [0,1])`. The core maps each `FeedFrame.kind` you yield to this event and salience. A `kind` not in this map is dropped with a debug log. | `{"proprio": ("mundus.proprio", 0.3), "frame": ("mundus.visual.raw", 0.1)}` |
| `action_families` | symbolic family → **default exposure** (bool). World-mutating or consent-sensitive verbs should default `False`; the operator opts in. The core merges operator overrides on top of these defaults. | `{"move": True, "say": True, "teleport": False}` |
| `continuous_channels` | Names of the clamped continuous channels this body supports (empty for symbolic-only). Must be drawn from the [canonical vocabulary](#the-canonical-continuous-channels). Must not repeat. | `("drive", "yaw_rate")` |
| `raw_buffer_keys` | Payload keys naming **raw sense buffers** the core must strip before publishing — the zero-raw-sense-data guarantee. | `("frame_bytes", "pcm")` |

Convention: use the existing `mundus.*` event names (`mundus.proprio`,
`mundus.chat`, `mundus.entity`, `mundus.visual.raw`, `mundus.notice`,
`mundus.action.result`, …) so downstream modules and the operator UI already
understand your feed. The `bridge.py` reference tables (`FEED_EVENT`,
`ACTION_DEFAULT_EXPOSED`) show a realistic transport-backed vocabulary you can crib
from.

---

## Perception (body → entity)

Your body produces perception by yielding `FeedFrame(kind, payload)` from `feed()`:

```python
async def feed(self) -> AsyncIterator[FeedFrame]:
    while self._running:
        msg = await self._read_one()          # your transport
        yield FeedFrame(kind="proprio", payload={"heading": msg.heading, ...})
```

The core's `_handle_feed` then, for each frame:

1. looks up `frame.kind` in `feed_events` → `(event_type, baseline_salience)`
   (unknown kinds are dropped);
2. copies the payload and **strips every key named in `raw_buffer_keys`** before
   anything reaches the bus;
3. applies the core-owned **salience policy** (e.g. a `proprio` frame with
   `dying`/`falling` is bumped to 0.8; an `entity` frame with `arrived` to 0.5);
4. publishes `event_type` with the stripped payload.

### The zero-raw-sense-data guarantee

This is a hard invariant, not a suggestion. Any rendered frame buffer, audio PCM,
or other raw sense bytes your body produces **must** be:

- declared by key in `raw_buffer_keys`, and
- **never persisted** by your adapter (hold it in memory, hand it to the vision/
  audio path in real time, and release it).

The core strips those keys so only *metadata* rides the bus and reaches disk. The
stub declares no raw buffers because it renders none; a camera-bearing body would
declare, e.g., `raw_buffer_keys=("frame_bytes",)` and put the encoded frame under
`payload["frame_bytes"]` for the vision path to consume off the side channel. If you
carry raw bytes in the payload and *forget* to declare the key, those bytes will be
published — the declaration is what enforces the guarantee.

---

## Action (entity → body)

There are two action paths, and the core chooses between them by intent type.

### Symbolic whole-action verbs → `apply_action`

`intent.avatar.<family>` intents from Volition (and the speech mirror's `say`) are
routed to `apply_action(family, params)` — but only when both:

1. the perceptual **locus is `virtual`** (`locus_reader()`); and
2. the family is **exposed** (descriptor default, overridable by operator config).

Symbolic families have no learned-policy producer today — they are operator-only
tools. Your adapter just needs to perform the verb and return `True`/`False`.

### Continuous per-tick control → `apply_setpoints`

The entity's per-tick motor command arrives as `intent.avatar.control` with the
channel scalars under `payload["channels"]`. The core's `_drive_control`:

1. **clamps and per-channel-gates** the channels (`_gate_channels`): a channel not
   on your body is dropped; an unexposed channel is dropped; the value is clamped to
   its declared range. **The producer is never trusted** — clamping and gating
   happen at the boundary, in the core, before your `apply_setpoints` is called.
2. calls `apply_setpoints(gated_channels)` with only the surviving, clamped
   channels;
3. publishes an **efference copy** on `mundus.efference` (a copy of what the entity
   emitted, clamped to range) so the forward model can close the loop.

Your `apply_setpoints` therefore receives an already-safe dict — you translate it to
your body's velocity/actuator commands and return `True`. A symbolic-only body
returns `False`, and the core logs the setpoints as unsupported.

#### The canonical continuous channels

The vocabulary and clamp ranges live in `kaine/modules/mundus/channels.py`
(`CONTINUOUS_CHANNEL_RANGE`). You may declare any subset:

| Channel | Range | Meaning |
|---|---|---|
| `drive` | `[-1, 1]` | Forward/back locomotion rate |
| `yaw_rate` | `[-1, 1]` | Turn rate (body heading) |
| `gaze_yaw` | `[-1, 1]` | Gaze horizontal rate — decoupled from the body |
| `gaze_pitch` | `[-1, 1]` | Gaze vertical rate — decoupled from the body |
| `interact` | `[0, 1]` | Single non-negative graded reach/interaction trigger |

(`strafe` is deliberately deferred and is not a channel.)

#### How the entity drives these, and how the loop closes

The producer is the **continuous embodiment control surface**
(`control_surface.py`, off by default). Its `ContinuousMotorSurface.emit()` runs the
entity's **learned** `MotorPolicy`, masks channels the freeze-then-free
`MotorCurriculum` has not yet freed, clamps the rest, and emits
`intent.avatar.control`. Each tick, the core drives your `apply_setpoints` **and**
publishes the efference copy; feeding that efference copy plus the proprioceptive
feedback your body returns (via your own `feed()` — e.g. resulting velocity/heading
on `mundus.proprio`) back through Soma's existing forward model is what makes this a
**closed loop** rather than an open-loop joystick. Your adapter's job in the loop is
simply: **accept clamped setpoints, and report the sensory consequence back through
`feed()`.** See [`modules/mundus.md`](../modules/mundus.md#continuous-embodiment-control-surface)
for the producer's internals.

---

## Gating your adapter must respect

Nothing your adapter does reaches the body unless every gate below passes. You do
**not** implement these — the core enforces them — but your adapter must be written
so it is safe when they are enforced (e.g. `open()` may never be called; actions may
be dropped).

| Gate | Rule |
|---|---|
| **Perceptual locus** | Actions and setpoints flow only when the locus is `virtual` (`perception_state.read_desired().locus`). In `physical` or `off`, in-world action is suppressed. Selecting `virtual` also turns off the real camera/mic (mutual exclusion). |
| **Two-layer operational gate** | The body is opened and driven only when **`[mundus].enabled = true`** (config layer) **AND** **`KAINE_MUNDUS_OPERATOR_APPROVED=1`** (operator/env layer). If either is absent, Mundus logs which gate failed and never calls `open()`. `[modules].mundus = true` is additionally required to construct the module at all. |
| **Per-family exposure** | Each symbolic family is gated by its exposure flag; world-mutating/consent-sensitive verbs default `False`. |
| **Per-channel exposure** | Every declared continuous channel defaults **unexposed** and is dropped until explicitly exposed. |

Design your descriptor defaults conservatively: expose only benign families and
channels by default, and let the operator opt into the rest.

---

## Wiring: selection and construction at boot

Adapters are constructed in `make_mundus` in `kaine/boot.py`. It:

1. reads `[mundus].adapter` (default `"stub"`);
2. reads that adapter's own nested `[mundus.<adapter>]` table for adapter-specific
   settings and `expose_<family>` overrides;
3. constructs exactly the selected adapter; **an unknown adapter name raises and
   fails closed** — no body is constructed.

To register a new adapter named `robot`, add a branch:

```python
# in make_mundus(), alongside the stub branch
if adapter_name == "stub":
    from kaine.modules.mundus.adapters.stub import StubAdapter
    adapter = StubAdapter()
elif adapter_name == "robot":
    from kaine.modules.mundus.adapters.robot import RobotAdapter
    adapter = RobotAdapter(**adapter_section)   # host/port etc. from [mundus.robot]
else:
    raise ValueError(f"mundus: unknown adapter {adapter_name!r}; ... (fail-closed)")
```

and select it in `config/kaine.toml`:

```toml
[mundus]
enabled = true
adapter = "robot"

[mundus.robot]
host = "127.0.0.1"
port = 5599
expose_move = true      # symbolic-family exposure override (merged over descriptor defaults)
```

> **Note on continuous-channel exposure:** `make_mundus` currently wires only the
> symbolic `expose_<family>` overrides from the adapter table into the core; the
> continuous per-channel exposure (`continuous_expose`) is a `Mundus` constructor
> argument and defaults every declared channel to **off**. To expose continuous
> channels today, pass `continuous_expose=` where the module is constructed (as the
> control-surface tests do). Keep the default-off posture: continuous channels are
> as consequential as world-mutating verbs.

---

## Testing: conformance-test a new adapter transport-free

The whole contract is exercisable **without any real body**. Model your tests on
`tests/test_mundus_module.py` and `tests/test_mundus_control_surface.py`, which drive
the core through the transport-free `StubAdapter` and a small in-file `FakeAdapter`.

The recipe:

1. **Descriptor sanity.** Construct your `capabilities()` and assert it — a malformed
   descriptor raises in `__post_init__`, so simply constructing it is a test. Assert
   your feed kinds, exposure defaults, channel set, and `raw_buffer_keys` are what you
   intend.
2. **Feed mapping + raw-strip.** Drive the core with your adapter, `push_frame` (or
   your test transport) a frame carrying a declared raw-buffer key, and assert the
   published `mundus.*` event has the key **stripped**. This is the zero-raw-sense-data
   guarantee, tested.
3. **Symbolic gating.** With `locus_reader=lambda: "virtual"`, publish an
   `intent.avatar.<family>` and assert `apply_action` recorded it; flip locus to
   `physical` (or leave a family unexposed) and assert it was dropped.
4. **Continuous path.** For a continuous-capable body, with
   `continuous_expose={"drive": True, ...}`, publish `intent.avatar.control` and
   assert your `apply_setpoints` received the **clamped, gated** channels and that a
   `mundus.efference` copy was published. See
   `test_producer_to_body_via_intent_bus` — it drives producer → control plane → body
   end to end over the `StubAdapter`, with no entity booted.
5. **Unsupported/symbolic-only.** If your body has no continuous channels, assert
   `apply_setpoints` returns `False` and the core treats setpoints as unsupported.

The core tests use a `fakeredis`-backed bus fixture and set
`KAINE_MUNDUS_OPERATOR_APPROVED=1` via `monkeypatch` — copy that fixture. Because
`EmbodimentAdapter` is `runtime_checkable`, you can also assert
`isinstance(adapter, EmbodimentAdapter)` as a structural conformance check.

---

## Worked example: a robot over a local socket

A minimal continuous-capable adapter for a robot base reached over a local TCP
socket. It steers with `drive`/`yaw_rate` and reports proprioception back. Copy it
to `kaine/modules/mundus/adapters/robot.py` and fill in the four `TODO`s.

```python
# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""Example embodiment adapter: a robot base over a local socket."""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from kaine.modules.mundus.adapter import EmbodimentCapabilities, FeedFrame


class RobotAdapter:
    """Drives a robot base over a length-prefixed local socket.

    Continuous-capable: steers with `drive`/`yaw_rate`, reports proprioception
    back so the entity's control loop can close. Symbolic `say` is a no-op here.
    """

    def __init__(self, *, host: str = "127.0.0.1", port: int = 5599, **_: Any) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._running = False

    # 1. What this body can do — read by the core, never hardcoded there.
    def capabilities(self) -> EmbodimentCapabilities:
        return EmbodimentCapabilities(
            name="robot",
            transitional=False,
            # feed kind -> (bus event, baseline salience). Reuse the canonical
            # mundus.* names so downstream modules already understand the feed.
            feed_events={
                "proprio": ("mundus.proprio", 0.3),
                "frame": ("mundus.visual.raw", 0.1),
            },
            # Symbolic verbs; default exposure. Keep consequential verbs False.
            action_families={"say": True},
            # Continuous channels this base supports (subset of the canonical five).
            continuous_channels=("drive", "yaw_rate"),
            # Raw sense buffers the core must STRIP before publishing, and that this
            # adapter must never persist. Declare every raw buffer you ever attach.
            raw_buffer_keys=("frame_bytes",),
        )

    # 2. Own the transport.
    async def open(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        self._running = True
        # TODO: any handshake your robot firmware expects.

    async def close(self) -> None:  # idempotent
        self._running = False
        if self._writer is not None:
            self._writer.close()
            self._reader = self._writer = None

    # 3. Perception: body -> core. Yield FeedFrames; never publish to the bus.
    async def feed(self) -> AsyncIterator[FeedFrame]:
        while self._running and self._reader is not None:
            msg = await self._read_message()   # TODO: your wire decode
            if msg is None:
                break
            # Proprioception closes the continuous loop; keys match MotorFeedback.
            yield FeedFrame(kind="proprio", payload={
                "forward_velocity": msg["v"],
                "heading": msg["heading"],
                "contact": msg["bumper"],
            })
            # If you attach a camera frame, put the bytes under a declared
            # raw_buffer_key so the core strips them before publish:
            # yield FeedFrame(kind="frame", payload={
            #     "w": 640, "h": 480, "encoding": "rgb8",
            #     "frame_bytes": jpeg,   # declared in raw_buffer_keys -> stripped
            # })

    # 4a. Symbolic sink (whole-action verbs). Gated by locus + exposure upstream.
    async def apply_action(self, family: str, params: dict[str, Any]) -> bool:
        if family == "say":
            # TODO: speak / display text on the robot.
            return True
        return False   # unknown family

    # 4b. Continuous sink. Channels arrive already CLAMPED and per-channel GATED
    # by the core — you just actuate them. Return False if you support none.
    async def apply_setpoints(self, channels: dict[str, float]) -> bool:
        drive = channels.get("drive", 0.0)
        yaw = channels.get("yaw_rate", 0.0)
        # TODO: map to your wheel velocities and write to the socket.
        await self._send({"cmd": "drive", "v": drive, "w": yaw})
        return True

    # --- your transport helpers -------------------------------------------------
    async def _send(self, obj: dict[str, Any]) -> None: ...   # TODO
    async def _read_message(self) -> dict[str, Any] | None: ...  # TODO
```

That is a complete, contract-conformant body. To bring it up: add the `robot` branch
to `make_mundus`, set `[mundus].adapter = "robot"` and its `[mundus.robot]` table,
pass the two-layer gate (`[mundus].enabled = true` + `KAINE_MUNDUS_OPERATOR_APPROVED=1`),
put the locus in `virtual`, and expose the channels/families you want. Then
conformance-test it transport-free exactly as the stub is tested.

---

## Checklist

- [ ] Descriptor declares `feed_events`, `action_families` (conservative defaults),
      `continuous_channels` (canonical subset), and **every** `raw_buffer_keys`.
- [ ] `feed()` yields `FeedFrame`s and never publishes to the bus; raw buffers are
      declared and never persisted.
- [ ] `apply_action` performs symbolic verbs; `apply_setpoints` actuates the
      already-clamped/gated channels (or returns `False` for a symbolic-only body).
- [ ] `open`/`close` own the transport; `close` is idempotent.
- [ ] Registered in `make_mundus`; unknown names still fail closed.
- [ ] Conformance-tested transport-free against the core, modeled on
      `tests/test_mundus_module.py` and `tests/test_mundus_control_surface.py`.

## See also

- [Mundus module](../modules/mundus.md) — the control plane, gating, and the
  continuous control surface.
- [Perception locus](../processes/perception-locus.md) — the physical-XOR-virtual
  gate your actions obey.
- [Configuration reference](../configuration.md#mundus) — `[mundus]`,
  `[mundus.control_surface]`, and adapter tables.
- `kaine/modules/mundus/adapters/stub.py` — the shipped reference body to copy.
