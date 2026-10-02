# Embodiment adapters

An embodiment adapter connects a body to a KAINE entity. The body may be a physical robot, a simulator, a VR avatar, or any custom effector. The adapter implements one narrow interface and declares what the body can perceive and do, without touching the cognitive core, the bus, or the workspace. Operators wiring an existing adapter and contributors adding a new one should read this page. Read [Mundus](09-modules/mundus.md) first for the control-plane overview.

## What an adapter is

Mundus is a body-agnostic control plane. It routes perception and action between the entity and a body, and owns the contract: gating, perceptual locus, intent routing, the speech mirror, salience policy, and the zero-raw-sense-data guarantee. The core knows no wire protocol, transport, or platform vocabulary.

A body is a small adapter that:

- implements the `EmbodimentAdapter` protocol in [`kaine/modules/mundus/adapter.py`](../kaine/modules/mundus/adapter.py);
- declares an `EmbodimentCapabilities` descriptor that tells the core, at runtime, what the body can perceive and do.

```
 entity ──intent.avatar.*──▶  Mundus core  ──apply_action / apply_setpoints──▶  YOUR ADAPTER ──▶ body
 entity ◀──mundus.* events──  Mundus core  ◀──────── feed() yields FeedFrame ───  YOUR ADAPTER ◀── body
```

The core reads the descriptor instead of hardcoding any platform's tables, so adding a body never touches the core. You add one file under [`kaine/modules/mundus/adapters/`](../kaine/modules/mundus/adapters/), register it in [`kaine/boot.py`](../kaine/boot.py), and select it in [`config/kaine.toml`](../config/kaine.toml).

The shipped reference body is the transport-free stub in [`kaine/modules/mundus/adapters/stub.py`](../kaine/modules/mundus/adapters/stub.py). It pins the whole protocol, including the continuous-control path, with no socket and no external dependency. Use it as a template and as a conformance-test baseline. A virtual-world (Paracosmic) adapter is planned behind the same contract; only the old Kosmos connector design was archived as superseded. The only adapter that ships today is `stub`.

## The `EmbodimentAdapter` protocol

[`kaine/modules/mundus/adapter.py`](../kaine/modules/mundus/adapter.py) defines the protocol the core drives every body through. It is `runtime_checkable`, so your adapter needs no base class. It only needs these members:

```python
class EmbodimentAdapter(Protocol):
    def capabilities(self) -> EmbodimentCapabilities: ...
    async def probe(self) -> bool: ...          # optional: reachability check without staying open
    async def open(self) -> None: ...          # bind/connect/spawn the transport
    async def close(self) -> None: ...          # tear it down; idempotent
    def feed(self) -> AsyncIterator[FeedFrame]: ...          # perception: body → core
    async def apply_action(self, family: str, params: dict) -> bool: ...   # symbolic sink
    async def apply_setpoints(self, channels: dict[str, float]) -> bool: ...  # continuous sink
```

| Method | Direction | What it does |
|---|---|---|
| `capabilities()` | — | Return the immutable capability descriptor. The core calls it on construction and on every feed/action, so keep it cheap and constant. |
| `probe()` (optional) | — | Test reachability without leaving the body open. Mundus calls it from `probe_available()` if it exists. |
| `open()` | — | Bind the socket, connect, or spawn the transport. Mundus calls it when the body is activated, which can happen during `probe_available()` or later when a dormant Mundus is activated. It is not guaranteed to run exactly once. |
| `close()` | — | Tear the transport down. Must be idempotent and must tolerate a `close()` after a probe-time `open()` that never started `feed()` or `apply_*`. |
| `feed()` | body → core | Yield `FeedFrame(kind, payload)` values until the body disconnects. The core pumps this in its own task and maps each frame to a bus event. Never publish to the bus yourself. |
| `apply_action(family, params)` | core → body | The symbolic sink: perform a whole-action verb (`move`, `say`, `gesture`, …). Return `True` if the command was sent. |
| `apply_setpoints(channels)` | core → body | The continuous sink: drive graded per-tick channels. Return `True` if sent; a symbolic-only body returns `False`. |

If an adapter does not implement `probe()`, Mundus tests availability by calling `open()` followed by `close()` from `probe_available()`.

### Which methods to implement

A symbolic-only body (a chat avatar, or a gripper with `open`/`close` commands) implements `apply_action`, and makes `apply_setpoints` return `False`. It declares `continuous_channels=()`.

A continuous-capable body (a robot base steered with velocities, or an avatar driven by a joystick-like signal) implements `apply_setpoints` over the canonical channels, and declares them in `continuous_channels`. It may also implement `apply_action` for whole-action verbs the same body supports.

Both sinks may coexist on one body. The core decides which to call based on the intent it receives.

## The `EmbodimentCapabilities` descriptor

`EmbodimentCapabilities` is a frozen dataclass. Your body uses it to tell the core what it can do. The descriptor is validated in `__post_init__`, so a malformed descriptor raises at construction.

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
| `name` | Adapter identity (non-empty). It matches the `[mundus].adapter` value that selects it. | `"robot"` |
| `transitional` | `True` marks a body expected to be retired, such as a reference or conformance body. `False` marks a real body. | `False` |
| `feed_events` | feed `kind` → `(bus event type, baseline salience in [0,1])`. The core maps each `FeedFrame.kind` to this event and salience. A `kind` not in this map is dropped with a debug log. | `{"proprio": ("mundus.proprio", 0.3), "frame": ("mundus.visual.raw", 0.1)}` |
| `action_families` | symbolic family → default exposure (bool). World-mutating or consent-sensitive verbs should default to `False`; the operator opts in. The core merges operator overrides on top. | `{"move": True, "say": True, "teleport": False}` |
| `continuous_channels` | Names of the graded continuous channels this body supports (empty for symbolic-only). The canonical vocabulary lives in `kaine/modules/mundus/channels.py`. `__post_init__` rejects repeats and empty names; unknown names are accepted and fall back to a default range of `(-1, 1)`. | `("drive", "yaw_rate")` |
| `raw_buffer_keys` | Payload keys naming raw sense buffers the core must strip before publishing. | `("frame_bytes", "pcm")` |

The current consumers of `mundus.*` feed events are the research observer (`mundus.proprio`, `mundus.scene`, `mundus.notice`) and Hypnos (`mundus.chat`). Reusing those names lets those modules consume your feed directly. Other event names are accepted, but nothing built-in listens to them.

## Perception

Your body produces perception by yielding `FeedFrame(kind, payload)` from `feed()`:

```python
async def feed(self) -> AsyncIterator[FeedFrame]:
    while self._running:
        msg = await self._read_one()          # your transport
        yield FeedFrame(kind="proprio", payload={"heading": msg.heading, ...})
```

For each frame, the core's `_handle_feed`:

1. looks up `frame.kind` in `feed_events` → `(event_type, baseline_salience)` (unknown kinds are dropped);
2. copies the payload and strips every key named in `raw_buffer_keys` before anything reaches the bus;
3. applies the core-owned salience policy (for example, a `proprio` frame with `dying`/`falling` is bumped to 0.8);
4. publishes `event_type` with the stripped payload.

### The zero-raw-sense-data guarantee

The zero-raw-sense-data guarantee is a hard invariant. Any rendered frame buffer, audio PCM, or other raw sense bytes your body produces must be:

- declared by key in `raw_buffer_keys`, and
- never persisted by your adapter (hold it in memory, hand it to the vision or audio path in real time, and release it).

The core strips those keys so only metadata rides the bus and reaches disk. The stub declares no raw buffers because it renders none. A camera-bearing body would declare, for example, `raw_buffer_keys=("frame_bytes",)` and put the encoded frame under `payload["frame_bytes"]` for the vision path to consume off the side channel. If you carry raw bytes in the payload and forget to declare the key, those bytes will be published. The declaration enforces the guarantee.

## Action

There are two action paths. The core chooses between them by intent type.

### Symbolic whole-action verbs

`intent.avatar.<family>` intents from Volition (and the speech mirror's `say`) route to `apply_action(family, params)` only when both conditions hold:

- the perceptual locus is `virtual` (`locus_reader()`); and
- the family is exposed (descriptor default, overridable by operator config).

Symbolic families have no learned-policy producer today. Your adapter performs the verb and returns `True` or `False`.

### Continuous per-tick control

The control seam receives motor commands as `intent.avatar.control` events with channel scalars under `payload["channels"]`. At runtime nothing publishes them automatically; tests and future cycle integrations exercise the path by publishing them directly.

The core's `_drive_control` handles the event in two ways:

- If the body declares no `continuous_channels`, the core forwards the raw dict to `apply_setpoints` before any locus check or clamping. A symbolic-only adapter must reject or ignore the dict itself.
- If the body declares channels, the core clamps and per-channel-gates them (`_gate_channels`): a channel not on the body is dropped; an unexposed channel is dropped; the value is clamped to its declared range. The locus gate is checked. The producer is never trusted; clamping and gating happen at the boundary, in the core, before `apply_setpoints` is called. The core then calls `apply_setpoints(gated_channels)` with the surviving, clamped channels and publishes an efference copy on `mundus.efference` with a `forwarded` flag.

Your `apply_setpoints` receives a clamped, gated dict only when the body declares channels. Translate it to your body's velocity or actuator commands and return `True`. A symbolic-only body returns `False`, and the core logs the setpoints as unsupported.

### Canonical continuous channels

The vocabulary and clamp ranges live in [`kaine/modules/mundus/channels.py`](../kaine/modules/mundus/channels.py) (`CONTINUOUS_CHANNEL_RANGE`). You may declare any subset:

| Channel | Range | Meaning |
|---|---|---|
| `drive` | `[-1, 1]` | Forward/back locomotion rate |
| `yaw_rate` | `[-1, 1]` | Turn rate (body heading) |
| `gaze_yaw` | `[-1, 1]` | Horizontal gaze rate, decoupled from the body |
| `gaze_pitch` | `[-1, 1]` | Vertical gaze rate, decoupled from the body |
| `interact` | `[0, 1]` | Single non-negative graded reach or interaction trigger |

`strafe` is deliberately deferred and is not a channel.

### How the loop closes

The continuous embodiment control surface in [`kaine/modules/mundus/control_surface.py`](../kaine/modules/mundus/control_surface.py) is built but inert at runtime. Its `emit()` returns a `ControlCommand`; it does not publish a bus event. `on_birth()` is not called by the runtime, so the surface stays dormant and nothing drives the per-tick loop.

When the loop is wired, the surface will run the entity's learned `MotorPolicy`, mask channels the freeze-then-free `MotorCurriculum` has not yet freed, clamp the rest, and hand the command to the core. The loop is closed by `EfferenceLoop.observe()` (via `observe_feedback`) on the surface's own `SubstrateForwardModel` instance, not on Soma's forward model. The core publishes the efference copy on `mundus.efference` with a `forwarded` flag; nothing consumes that event at runtime.

Your adapter's job is simple: when a control command reaches it, actuate the clamped, gated channels and report the sensory consequence back through `feed()` (for example, resulting velocity or heading on `mundus.proprio`). See [Mundus](09-modules/mundus.md) for the producer's internals.

## Gates your adapter must respect

Nothing your adapter does reaches the body unless every gate below passes. You do not implement these gates; the core enforces them. Your adapter must still be safe when they are enforced (for example, `open()` may never be called, and actions may be dropped).

| Gate | Rule |
|---|---|
| Perceptual locus | Symbolic actions and continuous commands for a body that declares `continuous_channels` flow only when the locus is `virtual` (`perception_state.read_desired().locus`). In `physical` or `off`, in-world action is suppressed. Selecting `virtual` also turns off the real camera and microphone (mutual exclusion). |
| Two-layer operational gate | The body opens and drives only when `[mundus].enabled = true` (config layer) and `KAINE_MUNDUS_OPERATOR_APPROVED=1` (operator/env layer). If either is absent, Mundus logs which gate failed and never calls `open()`. `[modules].mundus = true` is additionally required to construct the module at all. |
| Per-family exposure | Each symbolic family is gated by its exposure flag; world-mutating or consent-sensitive verbs default to `False`. |
| Per-channel exposure | Every declared continuous channel defaults unexposed and is dropped until explicitly exposed. |

If the body declares no `continuous_channels`, the core forwards raw setpoints to `apply_setpoints` before the locus check. That adapter must guard itself.

Design your descriptor defaults conservatively: expose only benign families and channels by default, and let the operator opt into the rest.

## Wiring at boot

Adapters are constructed in `make_mundus` in [`kaine/boot.py`](../kaine/boot.py). It:

1. reads `[mundus].adapter` (default `"stub"`);
2. reads that adapter's own nested `[mundus.<adapter>]` table for adapter-specific settings and `expose_<family>` overrides;
3. constructs exactly the selected adapter. An unknown adapter name raises and fails closed: no body is constructed.

Mundus may be created dormant during gestation and only call `open()` later, when `activate()` runs. During `probe_available()`, Mundus uses the adapter's optional `probe()` method; if the adapter lacks one, Mundus calls `open()` and then `close()` to test reachability. `close()` must tolerate that probe-time open.

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

Select it in [`config/kaine.toml`](../config/kaine.toml):

```toml
[mundus]
enabled = true
adapter = "robot"

[mundus.robot]
host = "127.0.0.1"
port = 5599
expose_move = true      # symbolic-family exposure override (merged over descriptor defaults)
```

`make_mundus` routes each `expose_<name>` key by your descriptor: a declared continuous channel goes to continuous exposure, a declared action family to symbolic exposure, and any other name refuses boot with the body's declared names in the error. Every continuous channel defaults to off. Keep that posture: continuous channels are as consequential as world-mutating verbs.

## Testing a new adapter

The whole contract is exercisable without any real body. Model your tests on [`tests/test_mundus_module.py`](../tests/test_mundus_module.py) and [`tests/test_mundus_control_surface.py`](../tests/test_mundus_control_surface.py), which drive the core through the transport-free `StubAdapter` and a small in-file `FakeAdapter`.

The recipe:

1. Descriptor sanity. Construct your `capabilities()` and assert it. A malformed descriptor raises in `__post_init__`, so simply constructing it is a test. Assert your feed kinds, exposure defaults, channel set, and `raw_buffer_keys` are what you intend.
2. Feed mapping and raw-strip. Drive the core with your adapter, push a frame carrying a declared raw-buffer key, and assert the published event has the key stripped. That tests the zero-raw-sense-data guarantee.
3. Symbolic gating. With `locus_reader=lambda: "virtual"`, publish an `intent.avatar.<family>` and assert `apply_action` recorded it. Flip locus to `physical`, or leave a family unexposed, and assert it was dropped.
4. Continuous path. For a continuous-capable body, with `continuous_expose={"drive": True, ...}`, publish `intent.avatar.control` and assert `apply_setpoints` received the clamped, gated channels and that a `mundus.efference` copy with a `forwarded` flag was published. `test_producer_to_body_via_intent_bus` drives producer → control plane → body end to end over the `StubAdapter`, with no entity booted.
5. Unsupported/symbolic-only. If your body has no continuous channels, assert `apply_setpoints` receives the raw dict and the core treats setpoints as unsupported when you return `False`.
6. Probe and lifecycle. If you implement `probe()`, assert it does not leave the adapter open and that `close()` is safe after a probe-time `open()`. Assert a dormant Mundus calls `open()` only after `activate()`.

The core tests use a `fakeredis`-backed bus fixture and set `KAINE_MUNDUS_OPERATOR_APPROVED=1` via `monkeypatch` (copy that fixture). Because `EmbodimentAdapter` is `runtime_checkable`, you can assert `isinstance(adapter, EmbodimentAdapter)` as a structural conformance check.

## Worked example of a robot over a local socket

A minimal continuous-capable adapter for a robot base reached over a local TCP socket. It steers with `drive` and `yaw_rate`, and reports proprioception back. Copy it to `kaine/modules/mundus/adapters/robot.py` and fill in the four `TODO`s.

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

    # 1. What this body can do: read by the core, never hardcoded there.
    def capabilities(self) -> EmbodimentCapabilities:
        return EmbodimentCapabilities(
            name="robot",
            transitional=False,
            # feed kind -> (bus event, baseline salience). Use names that the
            # current consumers already understand: the research observer reads
            # mundus.proprio / mundus.scene / mundus.notice, and Hypnos reads mundus.chat.
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

    async def probe(self) -> bool:
        """Optional reachability check: open, report success, and close."""
        try:
            _, writer = await asyncio.open_connection(self._host, self._port)
            writer.close()
            await writer.wait_closed()
            return True
        except OSError:
            return False

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

    # 4b. Continuous sink. If the body declares continuous channels, the core
    # clamps and gates them before calling this method. Return False if you
    # support none.
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

The adapter above is a complete, contract-conformant body. To bring it up: add the `robot` branch to `make_mundus`, set `[mundus].adapter = "robot"` and its `[mundus.robot]` table, pass the two-layer gate (`[mundus].enabled = true` and `KAINE_MUNDUS_OPERATOR_APPROVED=1`), put the locus in `virtual`, and expose the channels and families you want. Then conformance-test it transport-free exactly as the stub is tested.

## Checklist

- [ ] Descriptor declares `feed_events` using names the current consumers understand, conservative `action_families` defaults, a canonical subset of `continuous_channels`, and every `raw_buffer_keys`.
- [ ] `feed()` yields `FeedFrame`s and never publishes to the bus; raw buffers are declared and never persisted.
- [ ] `apply_action` performs symbolic verbs; `apply_setpoints` actuates clamped, gated channels when the body declares channels, or returns `False` for a symbolic-only body (and defends itself against the raw dict the core forwards in that case).
- [ ] `open` and `close` own the transport; `close` is idempotent and survives a probe-time `open()`.
- [ ] Optional `probe()` is implemented and leaves the transport closed.
- [ ] Adapter is registered in `make_mundus`; unknown names still fail closed.
- [ ] Adapter is conformance-tested transport-free against the core, modeled on [`tests/test_mundus_module.py`](../tests/test_mundus_module.py) and [`tests/test_mundus_control_surface.py`](../tests/test_mundus_control_surface.py).

## See also

- [Mundus module](09-modules/mundus.md): the control plane, gating, and the continuous control surface.
- [Perception locus](08-cognitive-cycle/perception-locus.md): how KAINE chooses between physical and virtual perception.
- [Configuration reference](appendix-a-configuration/modules.md): `[mundus]`, `[mundus.control_surface]`, and adapter tables.
- [`kaine/modules/mundus/adapters/stub.py`](../kaine/modules/mundus/adapters/stub.py): the shipped reference body to copy.
