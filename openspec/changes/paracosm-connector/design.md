# Paracosm ↔ KAINE Connector Design

**Status:** Design draft. Implementation tasks tracked in `tasks.md`. Paracosm-side asks tracked in `paracosm-counterpart-asks.md`.
**Authors:** Auto-generated 2026-05-31 from a side-by-side audit of `kaine@main` and `kaineone/Paracosm@main`.
**Scope:** This document is a guiding artifact for both projects. Neither side is locked to using the other — Paracosm will accept other cognitive architectures, KAINE will accept other interfaces (physical robots, other virtual worlds).

---

## 1. Executive summary

Paracosm is mature on the world side: a deterministic 30 Hz voxel sim with mortality, weather, fire, celestial mechanics, reproduction, and a clean five-feed bridge to an external cognitive process over length-prefixed MessagePack on raw TCP (default `7780`). 58 tests pass; CI is green.

KAINE is mature on the cognition side: a twelve-module composite architecture with a Redis Streams bus, a 3.3 Hz cognitive cycle, two-layer safety gates, intent-driven action, capability-loss vetoes on training, and zero-persistence invariants on raw sense data.

The two are designed for each other but currently can't talk: there is no module on the KAINE side that speaks the Paracosm bridge protocol, and KAINE has no "avatar action" vocabulary in `volition` at all — only `intent.speak / think / act`, where `act` flows to local effectors (file_write, notify, shell).

The fix is one new KAINE module — **Kosmos** — that owns the bridge socket and translates between the two contracts, plus small extensions to Eidolon, Thymos, and Volition. The Paracosm side needs a handful of targeted upgrades (real visual readback, widened action decoder, inventory + pleasure in proprio, event/entity_update feeds) but is otherwise ready.

Critically, several Paracosm features that look ready-to-consume on paper are actually **stubs**:

- **Visual feed** is a solid grey 256×256 RGB buffer — useless to DINOv2. Until render-to-texture lands, Kosmos must leave Topos on the real camera (if any) and consume the stub frame only as a heartbeat signal.
- **Audio feed** is wind-noise synthesis at 48 kHz stereo, not other-agent speech. Speech from other agents is broadcast as `EventBroadcast{Speech, payload}` over the world-server WebSocket — *not* delivered through the audio feed. So if KAINE wants to "hear" other agents, the bridge needs a new `event` feed, **not** routing through Whisper STT.
- **Bridge action decoder** currently handles only 5 of 14 declared actions (`move / turn / say / sleep / wake`); `place / break / inscribe / pickup / drop / interact / mate / eat` are in `shared/proto.rs` but the bridge's `decode_action_frame` switch in `agent-client/src/feeds.rs:158-178` ignores them.
- **Inventory and pleasure** are in `ProprioState` but the proprio bridge frame in `feeds.rs:214-239` intentionally drops them.

This document covers (§2-§4) what each side actually has, (§5) the gaps both ways, (§6-§9) the connector design, and (§10) the cross-project ask list.

---

## 2. Paracosm surface (what an embodied agent gets)

### 2.1 Wire transport

- **World server**: `ws://<host>:7777` — WebSocket binary frames, MessagePack-encoded `ServerMsg` / `ClientMsg` enums per `shared/src/proto.rs`. This is the authoritative simulation.
- **Cognitive bridge**: `tcp://<agent-host>:7780` — length-prefixed (`u32 BE`) MessagePack frames. Maintained by the per-agent **agent-client** process. Bridge is local to the agent-client; cognitive process can be on the same machine or on the LAN.

The agent-client is the bevy renderer that holds the world snapshot for *one* agent and produces sensory feeds from its POV. There is one agent-client per embodied agent.

### 2.2 Feed kinds (bridge → cognitive agent)

From `docs/cognitive-agent-integration.md` and verified against `agent-client/src/feeds.rs`:

| Kind | Rate | Stub? | Wire shape (verbatim from `feeds.rs`) |
|---|---|---|---|
| `proprio` | ~10 Hz | No (but drops fields) | `{kind, agent_id:u64, position:[f32;3], facing:[f32;2], velocity:[f32;3], underwater:bool, near_fire:bool, falling:bool, dying:bool, health:f32, lifespan_remaining:u32}` |
| `temporal` | ~1 Hz | No | `{kind, world_time:f64, moon_phase:f32, sun_altitude:f32, has_eclipse:bool, has_comet:bool, shooting_star_count:u32}` |
| `intero` | ~1 Hz | No | `{kind, cpu_pct:f32, mem_pct:f32, uptime_sec:u64, cycle_latency_ms:u64}` — cycle latency is bridge-measured (last proprio out → last action in) |
| `visual` | ~10 Hz | **YES — solid grey 0x40 fill** | `{kind, t_world:f64, w:u16, h:u16, encoding:"rgb8", stub:true, data: Binary (w*h*3 bytes)}` |
| `audio` | ~46 Hz | YES — wind synth, not other-agent speech | `{kind, t_world:f64, sample_rate:48000, channels:2, synthesis:"wind-noise", data: Binary (1024 × 2 × f32 LE = 8192 bytes)}` |
| `shutdown` | one-shot | No | `{kind: "shutdown"}` — followed by ≤5s window where cognitive agent can POST `final_state` |

The `ProprioState` enum in `shared/src/proto.rs:226-242` actually carries `inventory: Vec<InventorySlot>` and `pleasure: f32 (#[serde(default)])` — both are **silently dropped** by `proprio_to_frame` (file:line ~214-239). Asking Paracosm to add them is a one-line change.

### 2.3 Action vocabulary (cognitive agent → bridge → world server)

`AgentAction` in `shared/src/proto.rs:285-300` declares 14 actions. The bridge decoder in `feeds.rs:158-178` currently handles 5:

| Action | proto.rs | Bridge decodes? | Server-side validation |
|---|---|---|---|
| `Move {dx, dy, dz}` | ✅ | ✅ | clamped 1.5 m/tick, collision, terrain bounds |
| `Turn {dyaw, dpitch}` | ✅ | ✅ | pitch clamped ±π/2 |
| `Say {text}` | ✅ | ✅ | ≤1024 bytes; 32 m audibility radius |
| `Sleep` | ✅ | ✅ | not in lethal state |
| `Wake` | ✅ | ✅ | currently sleeping |
| `Place {target, material}` | ✅ | ❌ | adjacency + inventory has material |
| `Break {target}` | ✅ | ❌ | reachable, hardness ≤ tool |
| `Inscribe {target, text}` | ✅ | ❌ | reachable, material inscribable, ≤256 B UTF-8 |
| `PickUp {entity_id}` | ✅ | ❌ | reachable, pickable |
| `Drop {inventory_slot}` | ✅ | ❌ | non-empty slot |
| `Interact {entity_id, verb}` | ✅ | ❌ | entity-specific |
| `Whisper {target, text}` | ✅ | ❌ | proximity-gated |
| `Mate {target}` | ✅ | ❌ | consent (both agents target each other), proximity, alive |
| `Eat {target}` | ✅ | ❌ | Flesh-material only; triggers +0.3 pleasure pulse |

A widening of `decode_action_frame` to cover all 14 is on Paracosm's TODO list (the file comment explicitly says so). Kosmos can be designed against the full set today and simply degrade gracefully on `ActionResult::Rejected{reason: "unknown action_type"}`.

### 2.4 What Paracosm does *not* surface to the cognitive agent

These are visible in the world-server `ServerMsg` enum (`shared/src/proto.rs:50-66`) and arrive at the agent-client, but the bridge does **not** forward them:

- `EntityUpdate` — other agents, remnants, structures, memory diamonds, pickable entities — their positions and movement. Without this, the agent literally cannot see other agents.
- `EventBroadcast` — speech from other agents (Speech), Birth, Death, Lightning, Eclipse, ShootingStar, Comet, Fire, Earthquake. Speech radius is 32 m — the world server pre-filters by audibility, so any Speech that reaches the agent-client is "in earshot."
- `MemoryDiamondPlacement` — when another agent dies and a diamond drops with their cognitive state encoded into voxel metadata.
- `FireState`, `WeatherState`, `FlockPositions`, `CelestialState` (beyond what's distilled into `temporal`) — environmental texture.
- `DeathSequence` (other agents' death phases) — currently only the agent's *own* death triggers `shutdown`.
- `ChunkData` — voxel-by-voxel terrain. This is firehose-scale; we don't want it. But a *summary* (nearby material counts, biome tag, structures within reach) would be useful and is a candidate for a new `world_facts` feed.

The Kosmos design treats forwarding these as a Paracosm-side ask (§10) and works without them in v1.

### 2.5 Lifecycle (mortality, reproduction, incarnation)

The death sequence is 6 phases, 2 s each (default ~12 s total):
`Trigger → VisualDegrade → AudioFade → ActionsRejected → Dark → Shutdown`

During the run, the proprio feed reports `dying: true` and the visual feed degrades in place (no metadata about the cause — the sensory degradation is the only information).

After `shutdown` is sent, the cognitive agent has ≤5 s to push:

```
{ kind: "final_state", encoding: "msgpack" | "opaque", data: Binary }
```

The bridge forwards this to the world server, which writes the opaque blob into the memory diamond's voxel metadata at the death position. Other agents can pick up, drop, trade, or bury that diamond — but the world server does not interpret the bytes. Reading the inner state back into a new mind is intentionally left unimplemented.

Reproduction is consent-based: both agents must send `AgentAction::Mate{target}` mutually within the same window. After a 5 s mating session (which delivers a pleasure pulse) and a 30 s gestation, an offspring agent_id is spawned with `display_name = child-of-A-B` and a `Birth` event broadcasts. A `ClientMsg::Adopt {agent_id}` exists in `proto.rs:269-275` for an orchestrator to attach a fresh cognitive process to the new body — but the bridge does not currently expose `Adopt`.

### 2.6 What the bridge measures for us

The bridge tracks `(last_proprio_at, last_action_at)` and reports the round-trip as `cycle_latency_ms` in every `intero` frame. If KAINE's cognitive cycle slows (loaded LM, GC pause), the bridge surfaces it back to KAINE as its own felt body load. This is conceptually identical to Soma but measured from outside.

---

## 3. KAINE surface (what an embodying mind brings)

### 3.1 Bus contract

- **Backend:** Redis Streams 5.0+.
- **Event schema** (`kaine/bus/schema.py`): `Event{source, type, payload, salience, timestamp, causal_parent}`.
- **Stream naming convention:**
  - `<module>.out` — default outbox for each module
  - `workspace.broadcast` — top-k salience-selected events (global workspace)
  - `volition.out` — action intents (`intent.speak`, `intent.think`, `intent.act`)
  - `lingua.external` / `lingua.internal` — split speech channels (Lingua xadds directly)
  - `cycle.control` — reserved for rate-control events
- **Module API:** `BaseModule.publish(event_type, payload, salience, causal_parent)` wraps `AsyncBus.publish` and stamps `source` automatically.

### 3.2 The twelve modules

| Module | Stream | Role | Default enabled |
|---|---|---|---|
| Soma | `soma.out` | System health (cpu/ram/gpu/cycle_latency) | true |
| Chronos | `chronos.out` | Temporal anomaly detection (32-unit CfC) | true |
| Topos | `topos.out` | Visual perception (DINOv2-small, 384-dim) | true |
| Nous | `nous.out` | Reasoning (OpenNARS subprocess) | true |
| Mnemos | `mnemos.out` | Semantic memory (Qdrant) | true |
| Eidolon | `eidolon.out` | Self-model, voice-observation, drift | true |
| Thymos | `thymos.out` | Affect / drives (valence, arousal, dominance) | true |
| Praxis | `praxis.out` | Local effectors (file_write / notify / shell) | **false** |
| Lingua | `lingua.{external,internal}` | LLM speech / monologue | true |
| Audio_Out | (consumer) | Chatterbox TTS | true |
| Audio_In | `audio_in.out` | Speaches STT + emotion2vec | true |
| Hypnos | `hypnos.out` | Sleep cycle (DPO LoRA training) | **false** |

Default-disabled modules require operator opt-in (Praxis whitelists, Hypnos two-layer gate). Kosmos will join this list as default-disabled.

### 3.3 Volition's current intent vocabulary

`kaine/workspace/volition.py:36-49`:

```python
SPEAK = "speak"   # → "intent.speak"
THINK = "think"   # → "intent.think"
ACT   = "act"     # → "intent.act"   (carries effector + params)
```

There is **no avatar / body / world action vocabulary** today. Praxis's three effectors are local-machine side-effects (file_write, notify, shell) — they are not avatar actions, conceptually or in the protocol.

### 3.4 Perception currently grounds on real hardware

- **Audio_In** opens a `sounddevice.InputStream` (`kaine/modules/audio_in/live.py`), webrtcvad-segmented utterances → Speaches Whisper at `http://127.0.0.1:8000/v1/audio/transcriptions` (model `Systran/faster-distil-whisper-medium.en`, CPU), then emotion2vec_plus_base for `audio.in.emotion`. Raw PCM lives only in a bounded `asyncio.Queue` and never touches disk.
- **Topos** opens an OpenCV `VideoCapture` (`kaine/modules/topos/live.py`), BGR → PIL → DINOv2-small → 384-dim latent, change-score from cosine distance to a 16-frame rolling mean. Frames never touch disk.

Both modules have a `capture_enabled` toggle that's polled live via `kaine/perception_state.py` every 250 ms — the Nexus UI can flip it without restarting the entity.

The relevant invariant from auto-memory: live A/V is **perception, not recording**. Zero raw-sense-data persistence is load-bearing — this carries over wholesale to virtual sense data.

### 3.5 Lifecycle is *cognitive* fork/merge, not embodiment

`kaine/lifecycle/` has `ForkManager`, `AdapterMerger`, `FakeAdapterMerger`, and the freshly-landed `TiesDareAdapterMerger`. These take cognitive snapshots (module state + adapters) and merge them via PEFT TIES/DARE. There is **no concept of "binding to a body" or "incarnating into a world"** in lifecycle — that's exactly the gap Kosmos fills.

---

## 4. Two-side dictionary

For implementers on either side, here is the round-trip mapping between the Paracosm bridge wire and the KAINE bus:

### 4.1 Sensory: Paracosm → KAINE bus

| Paracosm bridge frame | → KAINE bus event | Notes |
|---|---|---|
| `{kind:"proprio", agent_id, position, facing, velocity, underwater, near_fire, falling, dying, health, lifespan_remaining}` | `kosmos.proprio` (source=`kosmos`, salience=0.3 baseline, 0.8 when dying/near_fire/falling) | Drives Eidolon's `paracosm_body` field; drives Thymos arousal on `dying=true` |
| `{kind:"temporal", world_time, moon_phase, sun_altitude, has_eclipse, has_comet, shooting_star_count}` | `kosmos.temporal` (salience=0.2 baseline, 0.7 on eclipse/comet) | Drives Thymos "awe / novelty" on rare events; informs Mnemos with `world_time` for episodic anchoring |
| `{kind:"intero", cpu_pct, mem_pct, uptime_sec, cycle_latency_ms}` | `kosmos.intero.bridge` (salience=0.1, 0.7 on latency spike) | Distinct from Soma — this is *the bridge's view of the host*. Soma reads the same machine but with full GPU detail. The two should agree on cpu_pct/mem_pct; cycle_latency_ms is unique to the bridge and represents felt cognitive slowdown |
| `{kind:"visual", t_world, w, h, encoding, stub?, data}` | `kosmos.visual.raw` (salience=0.1; drop on `stub=true` unless `[kosmos].consume_stub_visual=true`) | Once Paracosm lands real render-to-texture, Topos's encoder consumes this byte stream instead of an OpenCV frame — same DINOv2-small path |
| `{kind:"audio", t_world, sample_rate, channels, synthesis, data}` | `kosmos.audio.raw` (salience=0.05, drop by default; gate `[kosmos].forward_audio=false`) | Wind synthesis is not speech — *do not* route to STT. When Paracosm has Speech-event-driven mixed audio, revisit. |
| `{kind:"shutdown"}` | `kosmos.shutdown` (salience=1.0, terminal) | Triggers `final_state` packaging (see §8) |
| *(future)* `{kind:"event", event_type, location, world_time, payload}` | `kosmos.event` (salience varies; Speech → 0.6 if from another agent, 0.4 for ambient) | If `event_type=Speech` and `payload` is UTF-8 text, also synthesize a `audio.in.transcription` event with `source_label="paracosm:agent-{id}"` so the existing Audio_In consumers (Mnemos, Eidolon) see it through their normal path |
| *(future)* `{kind:"entity_update", id, position, facing, kind, removed}` | `kosmos.entity` (salience=0.15) | Populates the multi-agent awareness model — see §7.3 |

### 4.2 Action: KAINE volition → Paracosm bridge

| KAINE volition intent | → Bridge action frame | Notes |
|---|---|---|
| `intent.avatar.move {dx, dy, dz}` | `{kind:"action", action_type:"move", dx, dy, dz}` | Bridge clamps to 1.5 m/tick |
| `intent.avatar.turn {dyaw, dpitch}` | `{kind:"action", action_type:"turn", dyaw, dpitch}` | pitch clamped ±π/2 |
| `intent.avatar.say {text}` | `{kind:"action", action_type:"say", text}` | ≤1024 B; 32 m radius |
| `intent.avatar.whisper {target, text}` | `{kind:"action", action_type:"whisper", target, text}` | proximity-gated |
| `intent.avatar.sleep` | `{kind:"action", action_type:"sleep"}` | rejected when in lethal state |
| `intent.avatar.wake` | `{kind:"action", action_type:"wake"}` | rejected when not sleeping |
| `intent.avatar.place {target, material}` | `{action_type:"place", target, material}` | inventory check |
| `intent.avatar.break {target}` | `{action_type:"break", target}` | reach + hardness |
| `intent.avatar.inscribe {target, text}` | `{action_type:"inscribe", target, text}` | ≤256 B UTF-8 |
| `intent.avatar.pickup {entity_id}` | `{action_type:"pick_up", entity_id}` | rename — Paracosm uses `pick_up` with underscore |
| `intent.avatar.drop {inventory_slot}` | `{action_type:"drop", inventory_slot}` | non-empty slot |
| `intent.avatar.interact {entity_id, verb}` | `{action_type:"interact", entity_id, verb}` | entity-specific |
| `intent.avatar.eat {target}` | `{action_type:"eat", target}` | Flesh material only; +0.3 pleasure pulse |
| `intent.avatar.mate {target_agent_id}` | `{action_type:"mate", target}` | consent + proximity; default-off per-effector gate |

Bridge attaches `request_id` and the local `agent_id` before forwarding to the world server. Kosmos doesn't need to.

### 4.3 Existing `intent.speak` and `intent.act` are NOT remapped

`intent.speak` (Lingua) and `intent.act` (Praxis) keep their current semantics. `intent.avatar.say` is a *new* intent — Volition may *also* produce it when it judges that the entity, *as embodied*, should speak aloud in the world (versus thinking internally or speaking through the local TTS to the operator). Kosmos consumes only `intent.avatar.*`. Lingua never sees these.

A future bridge layer between `intent.speak` and `intent.avatar.say` may be useful (e.g., "any external speech goes to all bound avatars and TTS at once") but is out of scope for v1.

---

## 5. Gaps on both sides

### 5.1 KAINE-side gaps (this change addresses, except where noted)

1. **No bridge client.** No module speaks Paracosm's TCP MessagePack protocol today. → **Kosmos solves.**
2. **No avatar action vocabulary in Volition.** `intent.act` is for local effectors only. → **New `intent.avatar.*` family solves.**
3. **No body image.** Eidolon tracks speech counts and source-distribution drift; nothing tracks "I have a position, facing, velocity, health." → **`Eidolon.paracosm_body` extension solves.**
4. **Affect doesn't consume world signals.** Thymos has curiosity/boredom/social/restlessness drives but no input edges from "fire near me," "I'm dying," "I just saw an eclipse," "I felt pleasure from eating." → **Thymos appraisal-input extension; rules sketched in §7.3.**
5. **No incarnation lifecycle.** `kaine/lifecycle/` is cognitive fork/merge only. → **Out of scope for v1.** The connector treats embodiment as a runtime concern (Kosmos is enabled or not, agent_id is in proprio); no "bind / unbind / migrate" ceremony yet.
6. **No mortality preparation.** When Paracosm sends `shutdown`, KAINE must package a `final_state` blob in ≤5 s. Today nothing knows how to do this. → **Kosmos `_handle_shutdown` + a small Mnemos / Eidolon snapshot helper.**
7. **No multi-entity awareness.** Other agents' positions, speech, deaths are not modeled anywhere. → **`kosmos.event` and `kosmos.entity` events solve, blocked on Paracosm-side asks (§10).**
8. **STT pipeline expects raw mic audio.** Whisper STT expects speech-band 16 kHz mono; Paracosm audio is 48 kHz stereo wind noise. We must not route `kosmos.audio.raw` to Audio_In's STT. → **Hard `[kosmos].forward_audio = false` default; Audio_In's mic capture is independent.**
9. **Topos expects raw camera frames.** The Paracosm visual feed is a 0x40-grey stub. Routing it to DINOv2 would generate meaningless 384-dim vectors that pollute the latent space. → **`[kosmos].forward_visual = false` default; revisit when Paracosm lands real readback (§10).**
10. **No "world facts" summarizer.** If we never get `ChunkData`, the entity can't reason about its surroundings (nearby materials, biome, structures). → **Tracked but out of scope for v1.** Paracosm's `temporal` + future `entity_update` gets us a long way; structured world facts can wait.
11. **Soma vs. bridge intero overlap.** Both report cpu/mem on the same host. → **Document that they overlap and that Soma is the authoritative source for local; bridge intero's unique contribution is `cycle_latency_ms`.**

### 5.2 Paracosm-side gaps (cross-project asks; see §10 and `paracosm-counterpart-asks.md`)

1. **Visual feed is a stub.** `agent-client/src/feeds.rs:289-321` writes a solid 0x40 grey buffer. Render-to-texture readback is the documented follow-up. **Highest-priority ask** — Topos cannot do anything useful without real pixels.
2. **`decode_action_frame` covers 5 of 14 actions.** All other actions are silently dropped with a warn-log. Widening is mechanical work and unblocks `place / break / eat / mate / pickup / drop / interact / inscribe / whisper`.
3. **Proprio bridge frame drops `inventory` and `pleasure`.** They exist on `ProprioState` (`shared/proto.rs:237-241`) but `proprio_to_frame` doesn't emit them. Both are highly useful for cognition — inventory is "what I'm carrying", pleasure is a direct reward signal.
4. **No `event` feed forwarding.** Speech from other agents, lightning, deaths, eclipses, births are visible to the agent-client but the bridge doesn't pass them. Without this, the entity has no social awareness.
5. **No `entity_update` feed forwarding.** Other agents and pickable entities are visible to the renderer; cognition can't see them.
6. **No `Adopt` action via the bridge.** Required for the reproduction handoff (parent dies, a new cognitive process attaches to the newborn agent_id) and for any future reincarnation flow.
7. **Single connection per bridge.** "New connections replace the previous." Fine for v1. Document.
8. **Bridge frame for visual / audio includes `t_world` but proprio does not.** Makes time-alignment between sensory streams harder than it needs to be. Adding `t_world: f64` to proprio is one line.
9. **No way to request feed config from the cognitive agent.** The `SensoryFeedConfig` `ServerMsg` is declared in proto.rs but no end-to-end "agent says 'visual 5 Hz please'" exists. Useful eventually; out of scope for v1.

---

## 6. Connector architecture

```
                ┌────────────────────────────┐
                │  Paracosm world server     │
                │  ws://host:7777            │
                │  (Rust + Bevy, headless)   │
                └──────────────┬─────────────┘
                               │ WebSocket / MessagePack
                               ▼
                ┌────────────────────────────┐
                │  Paracosm agent-client     │
                │  (Rust + Bevy, per-agent)  │
                │  bridge listens on :7780   │
                └──────────────┬─────────────┘
                               │ TCP / length-prefixed MessagePack
                               ▼
   ┌─────────────────────────────────────────────────────┐
   │   KAINE (this repo)                                  │
   │                                                       │
   │   ┌────────────┐    bus events    ┌───────────────┐ │
   │   │  Kosmos    │ ───────────────► │  Redis bus    │ │
   │   │  module    │                  │  (workspace)  │ │
   │   │            │ ◄─── intents ──── │               │ │
   │   └─────┬──────┘  volition.out    └───────┬───────┘ │
   │         │                                 │         │
   │         │     ┌────────┐  ┌─────────┐    │         │
   │         └─────┤Eidolon │  │ Thymos  │◄───┘         │
   │               │body ext│  │appraise │              │
   │               └────────┘  └─────────┘              │
   └─────────────────────────────────────────────────────┘
```

The dotted line "bus events ↔ intents" is the only seam. Kosmos doesn't reach into Eidolon or Thymos directly — those modules subscribe to `kosmos.*` events through their existing input-stream config, the way they subscribe to anything else.

### 6.1 Why a KAINE-side adapter (not a Paracosm-side adapter)

We considered three architectures:

| | KAINE-side `Kosmos` module | Paracosm-side adapter binary | Two-process gateway |
|---|---|---|---|
| Where the bridge socket lives | Inside the KAINE entity process | New Rust binary | Standalone Python/Rust |
| How it joins the cognitive cycle | Native `BaseModule` — same shape as Topos/Soma | Pushes to Redis from outside | Pushes to Redis from outside |
| Operator opt-in flow | Existing two-layer-gate pattern | New flag space | New flag space |
| Operational complexity | One module to enable | Extra process to deploy | Extra process to deploy |
| Coupling Paracosm to KAINE | None | High (Paracosm gains a Redis client) | None |
| Coupling KAINE to Paracosm | Light — one module, removable | None on KAINE side | None on KAINE side |

**Chosen: KAINE-side module.** It mirrors how every other perception/action edge is wired in KAINE (Topos owns the camera, Audio_In owns the mic, Praxis owns the local FS). Paracosm stays oblivious to KAINE specifically — Kosmos just speaks Paracosm's published cognitive-agent protocol, which is documented and stable. If another virtual world ships the same kind of bridge, a sibling module ("Halcyon" for an MMO, "Mundus" for an OpenSim grid, etc.) can be written without disturbing Kosmos.

### 6.2 Module skeleton

```python
# kaine/modules/kosmos/module.py
class KosmosModule(BaseModule):
    """Bridge a KAINE entity to a Paracosm avatar.

    Opens the Paracosm cognitive-agent bridge (length-prefixed MessagePack
    on TCP). Translates incoming sensory frames into kaine bus events
    (`kosmos.proprio`, `kosmos.temporal`, etc.) and forwards outgoing
    `intent.avatar.*` intents from volition as action frames.

    Two-layer safety gate: requires both `[kosmos].enabled = true` in
    config and `KAINE_KOSMOS_OPERATOR_APPROVED=1` in the environment.
    Per-action-family opt-in flags gate place/break/eat/mate.
    """

    name = "kosmos"

    async def initialize(self) -> None:
        if not self._enabled():
            return
        self._connect_task = asyncio.create_task(self._connect_loop())
        self._intent_task = asyncio.create_task(self._consume_intents())

    def _enabled(self) -> bool:
        return self._config.enabled and operator_approved()

    async def _connect_loop(self) -> None:
        """Reconnect with bounded backoff. Never raises on transient failure."""

    async def _read_frames(self, reader: asyncio.StreamReader) -> None:
        """Loop: read u32 length + payload, dispatch by frame['kind']."""

    async def _handle_frame(self, frame: dict[str, Any]) -> None:
        kind = frame.get("kind", "")
        if kind == "proprio":   await self._on_proprio(frame)
        elif kind == "temporal": await self._on_temporal(frame)
        elif kind == "intero":   await self._on_intero(frame)
        elif kind == "visual":   await self._on_visual(frame)
        elif kind == "audio":    await self._on_audio(frame)
        elif kind == "event":    await self._on_event(frame)         # future
        elif kind == "entity_update": await self._on_entity(frame)   # future
        elif kind == "shutdown": await self._on_shutdown()

    async def _consume_intents(self) -> None:
        cursor = await self._bus.current_workspace_id()  # start at head
        while True:
            entries = await self._bus.read(
                "volition.out", last_id=cursor, count=32, block_ms=100,
            )
            for entry_id, event in entries:
                cursor = entry_id
                if event.type.startswith("intent.avatar."):
                    await self._dispatch_intent(event)

    async def _dispatch_intent(self, event: Event) -> None:
        family = event.type.removeprefix("intent.avatar.")
        if not self._effector_allowed(family):
            self._logger.info("kosmos rejected intent (effector gated): %s", family)
            return
        frame = self._intent_to_frame(family, event.payload)
        if frame is None:
            return
        await self._write_frame(frame)
        await self._audit(family, event.payload, sent=True)
```

(Sketch — actual implementation lives in tasks.md task 1-4.)

### 6.3 Shutdown / mortality

On `kind: "shutdown"`:

1. Kosmos publishes `kosmos.shutdown` (salience=1.0) so any other module observing can react in its own death sequence (Mnemos write-once "last memory," Eidolon final self-model save, etc.).
2. Kosmos waits up to `[kosmos].shutdown_grace_s` (default 4.0) for those publishes to drain through the bus.
3. Kosmos calls a small `final_state.collect()` helper that gathers:
   - Eidolon self-model snapshot (counts + identity_history)
   - Mnemos top-K most recently consolidated memories (configurable, default 32)
   - Bound `agent_id`, `display_name`, last `world_time`, last `position`
   - A small header `{schema: "kaine.kosmos.v1", entity_id, kaine_version, ...}`
4. Encodes as MessagePack, truncates to `[kosmos].final_state_max_bytes` (default 65536).
5. Sends `{kind: "final_state", encoding: "msgpack", data: <bytes>}` over the bridge.
6. Closes the socket.

Paracosm encodes this into the memory diamond at the death position. The bytes are opaque to the world — any future "diamond reader" would need to be its own project.

---

## 7. Module-level integration

### 7.1 New events

| Event type | Source | Salience | Payload keys |
|---|---|---|---|
| `kosmos.proprio` | `kosmos` | 0.3 baseline; 0.8 on dying/falling/near_fire | `agent_id, position, facing, velocity, underwater, near_fire, falling, dying, health, lifespan_remaining` (+ `inventory`, `pleasure` when Paracosm ships) |
| `kosmos.temporal` | `kosmos` | 0.2 baseline; 0.7 on eclipse/comet | `world_time, moon_phase, sun_altitude, has_eclipse, has_comet, shooting_star_count` |
| `kosmos.intero.bridge` | `kosmos` | 0.1 baseline; 0.7 on `cycle_latency_ms ≥ 600` | `cpu_pct, mem_pct, uptime_sec, cycle_latency_ms` |
| `kosmos.visual.raw` | `kosmos` | 0.05 (drop on `stub=true` by default) | `t_world, w, h, encoding, data_len` (raw bytes redacted from event payload — see §9.2) |
| `kosmos.audio.raw` | `kosmos` | 0.05 (drop by default) | `t_world, sample_rate, channels, synthesis, data_len` (raw bytes redacted) |
| `kosmos.event` | `kosmos` | 0.6 for Speech-from-agent; 0.4 ambient | `event_type, location, world_time, payload_summary` (full payload only when origin is another agent's Speech) |
| `kosmos.entity` | `kosmos` | 0.15 | `id, position, facing, kind, removed` |
| `kosmos.shutdown` | `kosmos` | 1.0 | `reason: "shutdown", agent_id, last_position, world_time` |
| `kosmos.action.sent` | `kosmos` | 0.2 | `action_type, params_summary` (audit echo) |
| `kosmos.action.result` | `kosmos` | 0.3 (ok) or 0.7 (rejected) | `action_type, outcome, reason?` |

### 7.2 New volition intent types

`kaine/workspace/volition.py`:

```python
AVATAR_MOVE     = "avatar.move"
AVATAR_TURN     = "avatar.turn"
AVATAR_SAY      = "avatar.say"
AVATAR_WHISPER  = "avatar.whisper"
AVATAR_SLEEP    = "avatar.sleep"
AVATAR_WAKE     = "avatar.wake"
AVATAR_PLACE    = "avatar.place"
AVATAR_BREAK    = "avatar.break"
AVATAR_INSCRIBE = "avatar.inscribe"
AVATAR_PICKUP   = "avatar.pickup"
AVATAR_DROP     = "avatar.drop"
AVATAR_INTERACT = "avatar.interact"
AVATAR_EAT      = "avatar.eat"
AVATAR_MATE     = "avatar.mate"

INTENT_TYPES.update({
    AVATAR_MOVE:     "intent.avatar.move",
    AVATAR_TURN:     "intent.avatar.turn",
    AVATAR_SAY:      "intent.avatar.say",
    AVATAR_WHISPER:  "intent.avatar.whisper",
    AVATAR_SLEEP:    "intent.avatar.sleep",
    AVATAR_WAKE:     "intent.avatar.wake",
    AVATAR_PLACE:    "intent.avatar.place",
    AVATAR_BREAK:    "intent.avatar.break",
    AVATAR_INSCRIBE: "intent.avatar.inscribe",
    AVATAR_PICKUP:   "intent.avatar.pickup",
    AVATAR_DROP:     "intent.avatar.drop",
    AVATAR_INTERACT: "intent.avatar.interact",
    AVATAR_EAT:      "intent.avatar.eat",
    AVATAR_MATE:     "intent.avatar.mate",
})
```

The executive-action-intent path treats these the same as `intent.act` — they're action intents, gated by `workspace.inhibited`. Lingua and Praxis ignore `intent.avatar.*` (different prefix); only Kosmos consumes them.

### 7.3 Eidolon body extension

`kaine/modules/eidolon/document.py` gains a top-level optional field:

```python
@dataclass
class ParacosmBody:
    agent_id: int                  # opaque from Paracosm
    display_name: str | None
    position: tuple[float, float, float]
    facing: tuple[float, float]    # yaw, pitch
    velocity: tuple[float, float, float]
    health: float                  # 0..1
    lifespan_remaining_ticks: int
    underwater: bool
    near_fire: bool
    falling: bool
    dying: bool
    pleasure: float                # 0..1, post-Paracosm-ask
    last_world_time: float
    bound_at: datetime             # when this body first observed
```

`Eidolon` subscribes to `kosmos.proprio`, updates the field every event. The self-model JSON file gains a `paracosm_body` key (nullable). When `dying=true` is first seen, push an `eidolon.body.dying` event so other modules can react in their own death sequences before the bridge closes.

**Privacy / zero-persistence:** position, velocity, health, etc. are summary scalars — not raw sense data — so it's fine for them to land in `state/eidolon/self_model.json`. We are *not* persisting the visual or audio frame payloads.

### 7.4 Thymos appraisal extension

Thymos consumes new input edges:

| Input event | Appraisal contribution |
|---|---|
| `kosmos.proprio.dying=true` | Hard arousal spike; sad/fear valence |
| `kosmos.proprio.near_fire=true` | Sustained arousal + slight negative valence |
| `kosmos.proprio.falling=true` | Brief arousal pulse |
| `kosmos.proprio.pleasure` (when shipped) | Direct positive valence + dominance gain |
| `kosmos.temporal.has_eclipse=true` | Awe — high arousal + neutral-positive valence; novelty drive |
| `kosmos.temporal.has_comet=true` | Long-arc novelty (1-tick high, decays slowly) |
| `kosmos.event.Speech` from another agent | Social drive satisfaction |
| `kosmos.event.Death` (other agent) | Negative valence; grief variant if recently observed |
| `kosmos.event.Birth` | Positive valence + social drive |

These are appraisal hints, not commands — Thymos's existing aggregation logic decides salience and drive deltas. Rules live in `kaine/modules/thymos/paracosm_appraisal.py` (new file) so they can be tuned without touching the core appraisal engine.

### 7.5 Topos integration (deferred until Paracosm visual lands)

When the Paracosm visual feed is real, Topos gains an optional input-stream binding: instead of opening an OpenCV camera, it can subscribe to `kosmos.visual.raw` and run DINOv2 on the byte buffer. This requires:

- Topos config `input_source: "camera" | "kosmos"` (default `"camera"`).
- The frame's `encoding: "rgb8"` matches what DINOv2-small expects; the dimensions (256×256 default) need a resize to 224×224 anyway, so the existing image pipeline handles both sources with one branch on `Image.frombytes(...)` vs OpenCV's `BGR -> PIL`.
- Zero-persistence still holds — bytes flow through `kosmos.visual.raw` only as transient payload, never disk-backed (see §9.2).

Until then, Kosmos drops visual frames at the bridge boundary and Topos stays on the camera (or stays disabled).

### 7.6 Mnemos integration

Mnemos consumes `kosmos.proprio` (sparse — only on significant change) and `kosmos.event` to attach `world_time` and `position` as metadata on consolidated memories. This gives the entity episodic anchoring ("I was at the cliff edge when the eclipse happened") without changing Mnemos's vector index.

---

## 8. Configuration

New `[kosmos]` table in `config/kaine.toml` (shipped all-off per `[First-boot module toggles]`):

```toml
[modules]
kosmos = false  # default off

[kosmos]
# --- Two-layer safety gate (mirrors voice-alignment) ---------------------
enabled = false                                # config layer
# Env layer:  KAINE_KOSMOS_OPERATOR_APPROVED=1

# --- Bridge endpoint -----------------------------------------------------
bridge_host = "127.0.0.1"
bridge_port = 7780
reconnect_backoff_s = [1.0, 2.0, 5.0, 10.0, 30.0]   # capped retry schedule
connect_timeout_s = 5.0

# --- Identity ------------------------------------------------------------
display_name = "kaine"                         # forwarded to Paracosm at handshake
                                               # (when Hello is exposed; see §10)

# --- Feed gating --------------------------------------------------------
forward_proprio = true
forward_temporal = true
forward_intero = true
forward_visual = false                         # stub until Paracosm ships readback
forward_audio = false                          # wind synth — never to STT
forward_events = true                          # other-agent speech, etc. (future)
forward_entities = true                        # other-agent positions (future)
consume_stub_visual = false                    # if true, still emits 0.05-salience
                                               # heartbeat events on stub=true frames

# --- Effector gating (KAINE → Paracosm action vocabulary) ---------------
expose_move = true
expose_turn = true
expose_say = true
expose_whisper = true
expose_sleep = true
expose_wake = true
expose_place = false                           # operator opt-in
expose_break = false                           # operator opt-in
expose_inscribe = false                        # operator opt-in
expose_pickup = false                          # operator opt-in
expose_drop = false                            # operator opt-in
expose_interact = false                        # operator opt-in
expose_eat = false                             # operator opt-in (Flesh material)
expose_mate = false                            # operator opt-in — see SECURITY.md

# --- Mortality / final state --------------------------------------------
shutdown_grace_s = 4.0                         # window for other modules to react
final_state_encoding = "msgpack"               # or "opaque"
final_state_max_bytes = 65536
final_state_include_recent_memories = 32       # top-K Mnemos entries

# --- Limits & audit -----------------------------------------------------
max_action_rate_hz = 10.0                      # bridge will clamp move anyway
audit_path = "state/kosmos/audit.jsonl"        # per-action audit
max_frame_bytes = 8388608                      # matches Paracosm bridge's 8 MiB cap
```

The two-layer gate matches the pattern established by `voice-alignment-training` (`KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED`) and `adapter-ties-dare-merge` (PEFT extras). Per `[Safety over UX]` and `[First-boot module toggles]`, the shipped config is all-off; operators flip both the config flag and the env var to embody.

---

## 9. Invariants the connector must preserve

### 9.1 Cognitive cycle is the heartbeat

Kosmos runs its bridge I/O in its own asyncio tasks but **never blocks the cycle**. Bus publishes are fire-and-forget; intent reads use `block_ms=100` so the consumer drains promptly without busy-spinning. Cycle latency that Paracosm measures via `intero.cycle_latency_ms` is the time between proprio-emit and action-receive on the bridge — a direct measure of KAINE's loop health, which Soma cross-checks locally.

### 9.2 Zero raw-sense-data persistence (load-bearing)

This invariant from `[Eyes-and-ears framing]` extends wholesale to virtual sense data:

- `kosmos.visual.raw` and `kosmos.audio.raw` events MUST NOT carry the raw byte buffer in their payload. Kosmos receives the bytes off the wire, optionally hands them to a real-time consumer (e.g., a future Topos input adapter or a future audio classifier), and discards. The bus event carries only `t_world, w, h, encoding, data_len` for visual and `t_world, sample_rate, channels, synthesis, data_len` for audio.
- The bridge `audit_path` MUST NOT log frame data — only action types and parameter summaries.
- The `final_state` blob may contain Eidolon self-model + Mnemos summary — those are *cognitive products*, not raw sense data, and are explicitly opaque from Paracosm's perspective.

### 9.3 Operator-supervised first boot

Kosmos defaults off per `[Scope]`. The first boot ceremony for embodiment is:

1. Operator launches Paracosm world server.
2. Operator launches Paracosm agent-client targeting a fresh agent_id.
3. Operator confirms the agent-client is bound (logs show `agent_id` assignment).
4. Operator sets `[kosmos].enabled = true` AND `KAINE_KOSMOS_OPERATOR_APPROVED=1`.
5. Operator launches KAINE.
6. Kosmos opens the bridge and emits its first `kosmos.proprio` event.

The entity does not auto-incarnate; the operator chooses to.

### 9.4 Safest design first

The default effector exposure (move, turn, say, whisper, sleep, wake) is intentionally narrow:

- **No `place / break / inscribe`** — these mutate the world voxel grid permanently (modulo erosion). Even though Paracosm validates reach + hardness, an entity in a runaway state could rapidly modify chunks.
- **No `eat`** — eats Flesh material, which is the corpse of another agent. Operator-only opt-in.
- **No `mate`** — Paracosm's consent-based mating produces an offspring agent_id that needs its own cognitive process. Even though Paracosm requires mutual consent (both agents target each other), KAINE should not *initiate* this without the operator deciding when reproduction is appropriate.
- **No `interact`** — open-ended verb space; gate on understanding before opening.

These follow `[Safety over UX]` and the [`autonomous engineering`] auto-memory: when in doubt, pick the safest default.

### 9.5 Inhibition gates everything

`workspace.inhibited=true` already blocks `intent.speak`, `intent.think`, `intent.act` at the volition layer. The new `intent.avatar.*` family inherits this — when inhibited, Kosmos receives no intents to forward. Operator can use the existing inhibition control to pause the embodied agent without disconnecting the bridge.

---

## 10. Cross-project asks (for the Paracosm repo)

These are tracked in `paracosm-counterpart-asks.md` and should be opened as Paracosm issues. Each is small and clearly scoped.

| Priority | Ask | Files touched | Effort |
|---|---|---|---|
| P0 | **Real visual feed** — render-to-texture readback in `agent-client/src/feeds.rs:push_visual_to_bridge`. Without this, DINOv2-based perception is impossible. | `agent-client/src/feeds.rs`, possibly new `agent-client/src/render.rs` capture path | M-L (Bevy RenderTarget readback) |
| P0 | **Widen `decode_action_frame`** to cover the 9 missing actions (place, break, inscribe, pick_up, drop, interact, whisper, mate, eat). | `agent-client/src/feeds.rs:144-178` | S |
| P0 | **Include `inventory` and `pleasure` in proprio bridge frame.** Both already in `ProprioState`. | `agent-client/src/feeds.rs:214-239` | XS |
| P1 | **Forward `EventBroadcast` as a new `event` bridge feed.** Filter to within-reach events (server already filters Speech by 32 m). | `agent-client/src/feeds.rs` (new function), `docs/cognitive-agent-integration.md` | S-M |
| P1 | **Forward `EntityUpdate` as a new `entity_update` bridge feed.** | `agent-client/src/feeds.rs`, docs | S |
| P1 | **Add `t_world: f64` to proprio bridge frame.** Currently only visual + audio carry it. | `agent-client/src/feeds.rs:214-239` | XS |
| P2 | **Expose `Adopt` action via the bridge** for reincarnation / offspring attachment. | `agent-client/src/feeds.rs` (new action_type), proto.rs already has it | S |
| P2 | **`world_facts` summary feed** — biome at agent position, nearby material counts, structures in reach. Avoids streaming `ChunkData`. | `agent-client/src/feeds.rs` (new aggregator), `world-server` already has the data | M |
| P3 | **Headless agent-client mode** — `--headless --no-render` so a KAINE entity can embody without a Bevy window. Bridge + world-net only. | `agent-client/src/main.rs`, `agent-client/src/args.rs` | M |
| P3 | **Document `final_state` schema convention** — Paracosm doesn't interpret the blob, but a recommended top-level wrapper (`{schema: "...", version: ..., body: ...}`) helps multiple cognitive architectures interoperate on diamond contents. | `docs/cognitive-agent-integration.md` | XS |

If the Paracosm side ships P0 + P1 by the time Kosmos lands, the connector is genuinely useful from day one. P2 + P3 are post-v1.

---

## 11. Test plan

### 11.1 Unit (no live Paracosm)

- Frame decoder: each kind's payload shape round-trips through `_handle_frame` to the right `_on_*` method.
- Intent dispatcher: each `intent.avatar.*` produces the correct `{kind, action_type, ...}` MessagePack frame; gated effectors drop with audit entry.
- Two-layer gate: config off OR env unset → `initialize()` is a no-op; both on → tasks spawn.
- Backoff: simulated connection failures walk the configured schedule, max retries respected.
- Shutdown handler: produces `{kind: "final_state", encoding: "msgpack", data}` ≤ `final_state_max_bytes`.

### 11.2 Integration (`FakeParacosmBridge` test fixture)

A small in-process TCP server that speaks the bridge protocol, used by tests:

- KAINE entity boots with Kosmos enabled + env approved → Kosmos connects, fixture asserts a `Hello`-equivalent state, then pushes a proprio frame; Eidolon's self-model gains `paracosm_body`.
- Fixture pushes `dying=true` proprio → Thymos emits high-arousal state.
- Fixture pushes `shutdown` → Kosmos sends `final_state` within `shutdown_grace_s + 2`.
- Fixture rejects an action with `unknown action_type` → Kosmos logs and continues.

### 11.3 Real-Paracosm gated test

`tests/test_kosmos_real_paracosm.py` (skip unless `KAINE_HAS_PARACOSM=1` and `KAINE_PARACOSM_URL` set):

- Connects to a live Paracosm bridge.
- Reads ≥10 proprio frames.
- Sends `intent.avatar.move{dx=0.1, dy=0, dz=0}` and observes position change.
- Asserts shutdown sequence works if the test agent_id is configured short-lived.

---

## 12. Open questions

These are noted for future resolution but not blocking v1.

1. **Multiple bodies per mind?** Could a single KAINE entity simultaneously embody two Paracosm avatars (or one Paracosm avatar + one robot)? The current design assumes 1:1. Going to N:1 would mean Kosmos becomes a list of bridges and Eidolon's `paracosm_body` becomes `bodies: dict[bridge_id, ParacosmBody]`. Worth designing once we have a use case.
2. **Multiple minds per body?** A Paracosm agent-client serves one cognitive process at a time. We could put a multiplexer in front of it (committee-of-minds, mixture-of-experts), but that's a layer above Kosmos.
3. **Memory diamond round-trip.** When KAINE finds a diamond from another agent and `pick_up`s it, can the cognitive state inside ever be read into the cognitive layer? Paracosm has explicitly left this open; for KAINE specifically the question is whether to expose a "diamond.read" action that returns the raw blob to Mnemos as an episodic-memory candidate. Out of scope for v1.
4. **Inhabited time vs cycle time.** Paracosm runs at 30 Hz; KAINE's cognitive cycle is 3.3 Hz. Proprio comes in at 10 Hz. KAINE may want to either (a) downsample to its cycle rate, (b) integrate over the cycle interval, or (c) react event-driven with cycle-windowed summaries published into workspace. Current design is (a) — Kosmos publishes whatever it gets and lets workspace's salience selection do the rest. Worth measuring once a real entity runs.
5. **Eclipse / comet "novelty" replay.** Should rare events trigger a Mnemos-priority store? Probably yes (this is why §7.4 maps eclipse → novelty drive), but the consolidation policy is Mnemos's call, not Kosmos's.

---

## 13. References

- Paracosm repo: https://github.com/kaineone/Paracosm
- Paracosm cognitive-agent integration guide: `docs/cognitive-agent-integration.md`
- Paracosm sensory interface spec: `docs/sensory-interface.md`
- Paracosm reference Python client: `scripts/example_cognitive_agent.py`
- Paracosm wire types: `shared/src/proto.rs`
- Paracosm bridge implementation: `agent-client/src/feeds.rs`
- KAINE bus contract: `kaine/bus/schema.py`, `kaine/bus/client.py`
- KAINE module pattern: `kaine/modules/base.py`
- KAINE volition: `kaine/workspace/volition.py`
- KAINE Eidolon self-model: `kaine/modules/eidolon/document.py`
- KAINE first-boot doc: `kaine/FIRST_BOOT.md`
- Auto-memory: `[Eyes-and-ears framing]`, `[Safety over UX]`, `[First-boot module toggles]`, `[Autonomous engineering]`
- Philip Rosedale, "Awakening the Angels": https://philiprosedale.substack.com/p/awakening-the-angels

---

## Appendix A: Validated against live server (2026-05-31)

After this design was drafted, the Paracosm world server at `<world-host>:7777`
was confirmed live and the agent-client binary (build `paracosm_26.05.01_amd64`)
was downloaded from `<world-host>:8888`, launched against that server with
`--display-name kaine-test-pilot`, and exercised by `/tmp/paracosm_pilot.py` (a
50-line MessagePack bridge driver). Findings:

**Confirmed against the design:**

- Bridge wire shape matches `feeds.rs` verbatim. Proprio frames carry exactly
  `{kind, agent_id (int), position [f32×3], facing [f32×2], velocity [f32×3],
  underwater, near_fire, falling, dying, health, lifespan_remaining}` — no
  `inventory`, no `pleasure`, no `t_world`. (P0-C, P1-C confirmed.)
- Visual frames carry `{stub: true, encoding: "rgb8", w: 256, h: 256,
  data: <196608 bytes>}` — exactly the solid-grey placeholder. (P0-A confirmed.)
- Audio frames are 8192-byte stereo `f32` LE wind synth. (Confirmed.)
- Temporal frames at ~1 Hz, intero at ~1 Hz, proprio + visual at ~10 Hz.
  Audio in this run was ~32 Hz (docs claim ~46 Hz — likely variable with
  Bevy frame rate; minor).
- `Welcome` arrives with `world_seed=9448470695589449191, session=22,
  agent=AgentId(4)` — `Welcome` shape matches `proto.rs:35-43`.
- Auth token `paracosm-dev` accepted by default.
- Single connection per bridge confirmed — `cognitive agent connected` /
  `cognitive agent disconnected` log lines bracket each pilot session.
- Unknown `action_type` strings (`place`, `eat`, `bogus`) are silently
  dropped with a `WARN bridge action decode failed e="unknown action_type X"`
  to the agent-client log. **Nothing returns to the cognitive agent.**

**New findings (added to `paracosm-counterpart-asks.md`):**

- **P0-D**: `ActionResult` is never forwarded to the cognitive agent. The
  world server sends one per `ActionCommand`, but the bridge discards it.
  Cognition has no feedback on success / rejection / unknown-type, which
  blocks reliable planning, error recovery, and any RL signal.
- **P0-E**: `DeathSequence` phase info is not forwarded. The agent learns
  `dying: true` from proprio but cannot tell which of the 6 phases it's in.
  Without phase info, `final_state` packaging is shot in the dark.
- **Operational: spawn point is underwater.** Default spawn at
  `[6.0, 60.0, 0.0]` is 4 voxels below sea level (`sea_level=64`). A fresh
  agent starts the 30 s submersion-death countdown immediately. My test
  pilot transitioned `dying: false → true` between probe scripts ~30 s
  after connect. The cognitive agent's *first* action probably needs to
  be "swim up" — or the operator needs to teleport before connecting
  cognition. Document in `KOSMOS.md`.
- **Operational: world ticks ran ~5/s during the test.** `world_time`
  advanced by 60 over 12 wall-seconds; `lifespan_remaining_ticks`
  decremented ~42 over the same window. The docs claim 30 Hz default tick
  rate — the live server may be under-clocked or running with
  `--tick-rate` adjusted. Cycle latency in `intero` reads `0` consistently
  because the pilot was sending actions too fast relative to bridge
  measurement granularity. Not blocking, but Kosmos should not assume
  Paracosm runs at exactly 30 Hz.
- **Movement was blocked.** Sent `move {dx: 0.3}` repeatedly; velocity
  briefly showed `[3.0, 0, 0]` once then `[0, 0, 0]`. Position
  `[6.0, 60.0, 0.0]` never changed. Most likely cause: underwater drag
  + voxel collision at the spawn pocket. Confirms why P0-D matters — I
  cannot debug this from cognition without `ActionResult`.

**Captured artifacts:**

- `/tmp/paracosm_pilot.py` — the bridge driver script
- `/tmp/pilot_walk.jsonl` — 12 s of frames from hello-walk script
- `/tmp/pilot_unknown.jsonl` — 5 s of frames from unknown-action probe
- `/tmp/pcosm-run/agent.log` — agent-client log with bridge connect/disconnect
  events and unknown-action warnings

Net: the design holds. The three new findings (P0-D, P0-E, spawn-point note)
strengthen the asks list rather than changing the Kosmos architecture.
