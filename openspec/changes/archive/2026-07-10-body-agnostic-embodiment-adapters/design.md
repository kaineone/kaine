# Design — Body-agnostic embodiment control plane with pluggable adapters

> **Design-of-record only.** The operator asked to **plan, not implement.** Code
> snippets are illustrative. Do not implement or boot an entity without a go.

## 1. Executive summary

Split today's OpenSim-bound Mundus into two layers along the line the paper already
draws: a **body-agnostic core** (Mundus proper) and a **platform adapter** (OpenSim
today, VR/paracosm or a robot later). The core owns the entity-facing contract —
gating, locus, intent routing, speech mirror, zero-persistence — and knows nothing
about any wire protocol. Each body is a small local `EmbodimentAdapter` the core
drives through one narrow interface plus a declared capability descriptor. The
existing OpenSim/LEAP bridge becomes the first adapter, behavior preserved. This is
the seam the paper's "each reached through a small local adapter" sentence requires,
and the thing that makes "drop OpenSim, add VR" a swap rather than a rewrite.

## 2. What is platform-specific today, and what is not

Reading `module.py` + `bridge.py`, the current module conflates two concerns:

**Body-agnostic (belongs in the core, keep):**
- Two-layer enable gate (`enabled` + `KAINE_MUNDUS_OPERATOR_APPROVED`).
- `locus == "virtual"` action gate via `perception_state`.
- Per-family exposure gating (`self._expose`).
- `intent.avatar.*` routing off the Volition stream; the speech mirror off
  `lingua.external`.
- Zero-raw-sense-data stripping (dropping the frame buffer before publish); salience
  bumps on notable events; the fire-and-forget publish that never blocks the cycle.
- Cursor seeding (only act on intents/speech formed after boot) and serialize/deserialize.

**Platform-specific (belongs in the OpenSim adapter, move):**
- The `asyncio.start_server` TCP listener and single-connection handling.
- The length-prefixed-MessagePack wire protocol (`bridge.py`).
- `FEED_EVENT` (OpenSim feed kinds → events) and `ACTION_DEFAULT_EXPOSED` (OpenSim
  verbs + defaults).
- The `say`/`move`/`sit_on`/… verb vocabulary and their `params` shapes.

The refactor is almost entirely a **move**, not a rewrite: the second list leaves the
module, the first stays, and a descriptor carries what the core used to hardcode.

## 3. The `EmbodimentAdapter` contract

One protocol, deliberately small (illustrative):

```python
class EmbodimentAdapter(Protocol):
    def capabilities(self) -> EmbodimentCapabilities: ...
    async def open(self) -> None: ...          # bind socket / connect / spawn transport
    async def close(self) -> None: ...
    def feed(self) -> AsyncIterator[FeedFrame]: ...   # perception: body → core
    async def apply_action(self, family: str, params: dict[str, Any]) -> bool: ...
    async def apply_setpoints(self, channels: dict[str, float]) -> bool: ...  # continuous
```

- `feed()` yields `FeedFrame(kind, payload)`; the core maps `kind` → (event, salience)
  via the descriptor and strips raw buffers. The adapter never publishes to the bus
  itself — it only produces frames — so zero-persistence and salience policy stay in
  one auditable place.
- `apply_action` is the symbolic sink (verbs). `apply_setpoints` is the continuous
  sink (VR-style graded channels). An adapter implements whichever its body supports and
  declares that in its descriptor; the core routes to the right sink.
- The adapter owns its transport (TCP+MessagePack for OpenSim; something else for a VR
  runtime), so the transport is never a core concern.

## 4. The capability descriptor

The core reads, rather than hardcodes, what a body can do:

```python
@dataclass(frozen=True)
class EmbodimentCapabilities:
    name: str                                   # "opensim", "paracosm-vr", …
    transitional: bool                          # true → expected to be retired
    feed_events: dict[str, tuple[str, float]]   # feed kind → (bus event, salience)
    action_families: dict[str, bool]            # symbolic family → default exposure
    continuous_channels: tuple[str, ...]        # e.g. (drive, yaw_rate, gaze_yaw, …)
    raw_buffer_keys: tuple[str, ...]            # payload keys to strip before publish
```

- `feed_events` replaces the module-level `FEED_EVENT`; `action_families` replaces
  `ACTION_DEFAULT_EXPOSED`. The OpenSim adapter declares exactly today's tables, so
  behavior is preserved by construction.
- `continuous_channels` is populated by adapters that support graded control. The
  OpenSim adapter leaves it empty (it is symbolic/autopilot); a VR adapter would declare
  `(drive, yaw_rate, gaze_yaw, gaze_pitch, interact)` — the same names
  `intuitive-embodiment-control-surface` specifies — so that change's producer wires to
  this seam with no core edit.
- `raw_buffer_keys` names the payload keys the core must strip (OpenSim: `data` on
  `frame`). Making it descriptor-driven keeps the zero-persistence guard adapter-aware
  rather than hardcoded to one wire shape.

## 5. Exposure and continuous-channel gating

Symbolic families gate exactly as today: `expose_<family>` must be true, the family
must be in the descriptor, and locus must be `virtual`. Continuous setpoints gate the
same way at the channel granularity: a per-channel exposure map (default all-off, like
the disruptive verbs) plus the locus gate, plus clamping each setpoint to its declared
range at the boundary (never trust the producer). A body that declares no continuous
channels simply cannot be driven by setpoints — the sink returns "unsupported" and the
core logs it, mirroring the "family not exposed" path.

## 6. Behavior preservation for the OpenSim path (the correctness bar)

The OpenSim adapter must be a pure lift. Concretely: same `bridge_host`/`bridge_port`
listener, same MessagePack frames, same `reqid` generation, same single-connection
"newest wins" semantics, same feed→event map, same default exposures, same salience
bumps, same speech-mirror `say` shape. The existing Mundus tests should pass with only
their construction updated to go through the adapter selection. A new test asserts the
OpenSim adapter's descriptor equals the old module constants, so a future edit that
drifts the OpenSim behavior fails CI. **Acceptance:** no observable change on the
OpenSim path; the diff is a move + an indirection.

## 7. Adapter selection and config

Replace the flat OpenSim-only `[mundus]` keys with adapter selection + a nested
adapter table:

```toml
[mundus]
enabled = false                 # shipped off (guard test still enforces this)
adapter = "opensim"             # which body; only this adapter is constructed
mirror_speech = true
speech_stream = "lingua.external"

[mundus.opensim]                # adapter-specific; ignored unless adapter = "opensim"
bridge_host = "127.0.0.1"
bridge_port = 7781
expose_move = true
expose_turn = true
expose_say = true
expose_sit_on = true
expose_stand = true
expose_animate = true
expose_gesture = true
expose_teleport = false
expose_touch = false
```

`boot.py` constructs only the selected adapter and injects it into `Mundus(...)`. An
unknown adapter name fails fast at boot (fail-closed), never silently binds nothing.

## 8. Supersession and migration

- `opensim-connector`'s embodiment/world-action/inbound-safety requirements are
  re-expressed here in platform-independent form; the OpenSim adapter is their concrete
  conformance. On approval, archive or annotate `opensim-connector` as superseded.
- `paracosm-connector`'s `Kosmos` sibling module is retired in favor of a future
  paracosm **adapter** (operator-confirmed fold). No adapter is designed here — the
  operator has not decided the rebuilt paracosm's VR control shape.
- `intuitive-embodiment-control-surface` keeps its intent; its continuous channels are
  now provided by the descriptor. Its dependency line re-points from `opensim-connector`
  to this change plus a live adapter.

## 9. Emergent-not-hardwired

Nothing here adds or removes entity behavior. The seam is pure plumbing: it relocates
platform code and reads capabilities from a descriptor. The provided-vs-emergent line
lives one layer up, in `intuitive-embodiment-control-surface` (the surface is provided,
the motor policy emerges). This change is careful to keep the continuous channels a
*shape the core can carry*, not a policy — it wires no producer and asserts no setpoint
values.

## 10. Resolved decisions (operator, 2026-07-05)

1. **OpenSim lifetime — FREEZE.** The OpenSim adapter stays as the seam's conformance/
   reference body but gets no further OpenSim feature work; it is removed cleanly once a
   VR/paracosm adapter is real. It is marked `transitional=True`.
2. **Continuous channels — FIXED NOW.** The canonical vocabulary is `drive`, `yaw_rate`,
   `gaze_yaw`, `gaze_pitch`, `interact` (the `intuitive-embodiment-control-surface` set),
   so every graded adapter and that change agree by construction.
3. **Superseded changes — ANNOTATE.** `opensim-connector` and `paracosm-connector` stay
   in place with a `superseded-by` note pointing here; not archived, so their design
   rationale keeps its provenance.
4. **Second adapter — BUILD A STUB NOW.** A minimal in-repo `stub` adapter is built
   alongside OpenSim: symbolic no-op families plus the five continuous channels, no
   transport, entirely local. It proves body-agnosticism with two real adapters and pins
   the protocol (including the continuous-channel path OpenSim does not exercise). It
   ships unselected and off; it is a reference/test body, not a real one.
