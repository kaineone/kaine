# Asks for the Paracosm side

These are gaps in Paracosm that block (P0) or limit (P1+) what a KAINE
entity (or any cognitive architecture using the bridge) can get from an
embodiment. Each is small in code terms — the build prompt's "Stub before
skip" convention already left explicit TODOs for most of them.

Open each as an issue against `kaineone/Paracosm` when the Kosmos
implementation starts on the KAINE side. None are KAINE-specific: any
cognitive architecture using the documented cognitive-agent bridge benefits
from them.

---

## P0 — Blocks meaningful embodiment

### P0-A: Real visual feed (render-to-texture readback)

**File:** `agent-client/src/feeds.rs:289-321` — `push_visual_to_bridge`
**Current state:** Emits a solid 0x40 grey RGB buffer (`stub: true` in the frame).
**Ask:** Replace with an actual capture of the agent camera's render target. Options:
- Bevy `RenderTarget::Image` with CPU readback path (`ImageCopyToBuffer`)
- Custom render graph node that copies the camera color attachment to a CPU-mapped buffer
- Or external GPU→CPU staging via `wgpu::Buffer::map_async`
**Why:** DINOv2-based perception (or any image model) needs real pixels. A solid grey frame produces meaningless embeddings that pollute downstream latent space.
**Effort:** M-L (Bevy RenderTarget readback has documented gotchas around `RenderApp`).
**Compat:** Once real, the `stub: true` flag goes away. Cognitive agents can detect this with `frame.get("stub", False)`.

### P0-B: Widen `decode_action_frame`

**File:** `agent-client/src/feeds.rs:144-178`
**Current state:** Only `move / turn / say / sleep / wake` are decoded — 5 of 14 actions in `AgentAction`. Other action_type strings get "unknown action_type" warn-log and are dropped.
**Ask:** Add cases for `place, break, inscribe, pick_up, drop, interact, whisper, mate, eat`. Wire shapes follow `shared/src/proto.rs:285-300` and `docs/cognitive-agent-integration.md`'s action table.
**Why:** Cognitive agents have full vocabulary documented; bridge silently truncates it.
**Effort:** S — mechanical pattern-match on each variant.
**Compat:** Strictly additive.

### P0-C: Include `inventory` and `pleasure` in proprio bridge frame

**File:** `agent-client/src/feeds.rs:214-239` — `proprio_to_frame`
**Current state:** `ProprioState` (`shared/src/proto.rs:226-242`) carries `inventory: Vec<InventorySlot>` and `pleasure: f32`, but `proprio_to_frame` doesn't emit them. **Empirically confirmed via 2026-05-31 live test** — proprio frames contain `agent_id, position, facing, velocity, underwater, near_fire, falling, dying, health, lifespan_remaining` only.
**Ask:** Append two more entries to the rmpv map:
```rust
("inventory".into(), rmpv::Value::Array(
    p.inventory.iter().map(|slot| rmpv::Value::Map(vec![
        ("material".into(), rmpv::Value::String(format!("{:?}", slot.material).into())),
        ("count".into(), rmpv::Value::Integer((slot.count as u64).into())),
    ])).collect(),
)),
("pleasure".into(), (p.pleasure as f64).into()),
```
**Why:** Inventory is "what I'm carrying", which gates `place / drop / inscribe` action validity. Pleasure is a direct reward signal a cognitive agent can use as appraisal input (mating, eating Flesh, etc., already drive it server-side).
**Effort:** XS — append two map entries.
**Compat:** Strictly additive (cognitive agents that ignore the new keys are unaffected).

---

### P0-D: Forward `ActionResult` to the cognitive agent

**File:** `agent-client/src/feeds.rs` (new feed kind), `world-server/src/network.rs` (already sends `ServerMsg::ActionResult`)
**Current state:** **Empirically discovered 2026-05-31** — the world server replies to every `ClientMsg::ActionCommand` with a `ServerMsg::ActionResult{request_id, agent_id, outcome: Ok|Rejected{reason}|Pending}` (per `shared/proto.rs:302-314`), but the agent-client bridge silently discards it. The cognitive agent has zero feedback on whether its actions succeeded.

Concretely: in the live test, I sent `move {dx: 0.3, dy: 0, dz: 0}` repeatedly. Velocity briefly showed `[3.0, 0, 0]` (likely one tick of clamped movement) then went back to `[0, 0, 0]`, and position never advanced from `[6.0, 60.0, 0.0]`. Almost certainly underwater drag or voxel collision blocked further motion — but I had no way to know that from the bridge. Even worse: I sent `place / eat / bogus` action_types deliberately to probe handling, and the bridge logged `WARN bridge action decode failed e="unknown action_type place"` to its own stdout but emitted nothing to me. From the cognitive agent's perspective, everything I sent was silently swallowed.

**Ask:** New feed kind, low rate (event-driven):
```
{ kind: "action_result",
  request_id: u64,                       // matches the request_id the bridge minted on send
  outcome: "ok" | "rejected" | "pending",
  reason: string?,                       // present when outcome=rejected
  client_request_id: u64?  }             // OPTIONAL: if the cognitive agent included a
                                         //   `request_id` in its action frame, echo it
                                         //   here so it can correlate without tracking
                                         //   the bridge's internal counter
```
Also fire `action_result` with `outcome="rejected", reason="unknown action_type X"` when `decode_action_frame` fails — so the cognitive agent learns which actions the bridge supports without out-of-band log inspection.

**Why:** Without this, cognition has to *infer* success from indirect proprio observation ("did position change after move?"). That fails for actions with delayed effects (place a voxel, then look later), actions that don't visibly change proprio (whisper, sleep), and actions the bridge can't even decode. A cognitive architecture cannot do reinforcement learning, error recovery, or even reliable planning against a silent action channel.

**Effort:** S-M — agent-client already receives `ServerMsg::ActionResult` (it must, to drain its socket); just route to bridge instead of dropping.

---

### P0-F: Fix `--headless` AssetServer panic

**File:** `agent-client/src/app.rs` (most likely)
**Current state:** **Empirically discovered 2026-05-31** with build `paracosm_26.05.01_amd64.deb`. The `--headless` flag exists and shows up in `--help`, but invoking it panics immediately:
```
thread 'main' (75026) panicked at .../bevy_asset/src/lib.rs:374:14:
Requested resource bevy_asset::server::AssetServer does not exist in the `World`.
    Did you forget to add it using `app.insert_resource` / `app.init_resource`?
    Resources are also implicitly added via `app.add_event`,
    and can be added by plugins.
```
The `--headless` path likely drops `AssetPlugin` along with `WindowPlugin` / `RenderPlugin`, but at least one downstream system still calls `world.resource::<AssetServer>()` unconditionally.
**Ask:** Either keep `AssetPlugin` even in headless mode (it's cheap; only the renderer is the heavyweight piece), or gate the offending system on a non-headless run-condition.
**Why:** This is the *only* way to run an embodied agent on a server box that doesn't have a display. Without it, every cognitive architecture using the bridge has to either run the agent-client on a workstation or jump through Xvfb + GPU passthrough hoops.
**Effort:** S (likely a one-line plugin add or a `run_if` guard).

**Workaround currently used:** Run the agent-client without `--headless` on a machine with X11 + a GPU. On the test box this worked because Vulkan + NVIDIA driver + a passive X server were available. KAINE's actual production host may not have that.

---

### P0-E: Forward `DeathSequence` phase info to the cognitive agent

**File:** `agent-client/src/feeds.rs` (new feed kind)
**Current state:** **Empirically discovered 2026-05-31** — the cognitive agent sees `dying: true` in proprio as soon as a lethal condition triggers, but cannot tell *which* of the 6 death phases it's in (`Trigger → VisualDegrade → AudioFade → ActionsRejected → Dark → Shutdown`, each ~2 s, ~12 s total). The world server broadcasts `ServerMsg::DeathSequence{agent_id, phase, intensity}` per `shared/proto.rs:198-204`, but the bridge doesn't forward.

In my live test the agent went `dying: true` (underwater spawn → 30 s submersion → death trigger), and that was all I knew. No `shutdown` arrived during the 5 s probe window because the death sequence runs ~12 s before reaching the final phase.

**Ask:** New feed kind:
```
{ kind: "death_sequence",
  agent_id: u64,
  phase: "trigger" | "visual_degrade" | "audio_fade" | "actions_rejected" | "dark" | "shutdown",
  intensity: f32   // 0.0 = unaffected, 1.0 = full degradation/silence
}
```
Send on every phase change. The existing `shutdown` one-shot stays as the trigger to start packaging `final_state`.

**Why:** Without phase info, the cognitive agent can't tune its final-state packaging to remaining wall-time. If we're at `Trigger` we have ~10 s; at `Dark` we have ~2 s. The current docs claim "a few seconds" but it's actually a deterministic countdown the agent could be aware of and plan against. Also: a cognitive agent in `ActionsRejected` phase will see its `move`/`say` get rejected — knowing why (we're dying, not that we made a bad request) is important for not training reinforcement signals on the rejection.

**Effort:** S.

---

## P1 — Limits multi-agent and event awareness

### P1-A: Forward `EventBroadcast` as a new `event` bridge feed

**File:** `agent-client/src/feeds.rs` (new function `push_events_to_bridge`)
**Current state:** `EventBroadcast` (Speech, Birth, Death, Lightning, Eclipse, ShootingStar, Comet, Fire, Earthquake) arrives at the agent-client; the bridge does not forward it. Speech is pre-filtered by the world server's 32 m audibility radius — anything that reaches the agent-client is in earshot.
**Ask:** New feed kind:
```
{ kind: "event", event_type: <string>, location: [f32;3]?, world_time: f64,
  payload: <bytes> | <decoded UTF-8 for Speech> }
```
Filter to events whose `location` is within a configurable radius of the agent (default 64 m for non-speech; 32 m for Speech matches the server filter).
**Why:** Without this, an embodied agent literally cannot hear another agent talk, witness a death, or notice lightning. Multi-agent cognition becomes impossible.
**Effort:** S-M (filtering is the only non-trivial part).

### P1-B: Forward `EntityUpdate` as a new `entity_update` bridge feed

**File:** `agent-client/src/feeds.rs` (new function `push_entities_to_bridge`)
**Current state:** Other agents' and pickable entities' positions are visible to the renderer but not forwarded to the cognitive agent.
**Ask:** New feed kind:
```
{ kind: "entity_update", id: u64, position: [f32;3], facing: [f32;2],
  kind: "agent"|"remnant"|"structure"|"other", removed: bool }
```
Forward all entities within a configurable visibility radius (default 32 m); send `removed: true` when an entity leaves the radius or despawns.
**Why:** Without this, an agent cannot know there's another agent at position X, can't gaze at them, can't approach them, can't decide to whisper to them.
**Effort:** S.

### P1-C: Add `t_world: f64` to proprio bridge frame

**File:** `agent-client/src/feeds.rs:214-239`
**Current state:** `visual` and `audio` frames carry `t_world`; `proprio` does not.
**Ask:** Append `("t_world".into(), snap.latest_celestial.world_time.into())` to `proprio_to_frame`.
**Why:** Time-aligning proprio with visual/audio frames currently requires separate clock reasoning. One line fixes it.
**Effort:** XS.

---

## P2 — Reincarnation, world facts

### P2-A: Expose `Adopt` via the bridge

**File:** `agent-client/src/feeds.rs:144-178` (decoder) + new ClientMsg path
**Current state:** `ClientMsg::Adopt {agent_id}` exists in `shared/src/proto.rs:269-275` for "orchestrator attaches a fresh cognitive process to an unclaimed agent_id (e.g. newly-born offspring)" but the bridge doesn't accept an `adopt` action_type.
**Ask:** New action_type:
```
{ kind: "action", action_type: "adopt", agent_id: u64, display_name: string? }
```
Bridge forwards as `ClientMsg::Adopt`.
**Why:** Required for the reproduction handoff (parent dies, new cognitive process attaches to the newborn) and for any future reincarnation flow where a KAINE entity wants to take over an unclaimed body.
**Effort:** S.

### P2-B: `world_facts` summary feed

**File:** `agent-client/src/feeds.rs` (new function)
**Current state:** `ChunkData` arrives at the agent-client (voxel-by-voxel terrain) but is firehose-scale and not forwarded. There's no condensed "what's around me" signal.
**Ask:** New feed kind, low rate (1 Hz):
```
{ kind: "world_facts", t_world: f64, biome: string,
  visible_materials: {Material: count},          // within 16 m radius
  nearby_structures: [{id, kind, position}],
  in_reach: [{material, position}],              // within 6 m reach
  sea_level: i32 }
```
**Why:** Avoids streaming `ChunkData` (firehose) while giving cognition spatial-context anchors. Lets the agent reason about "I'm in a forest, there's iron ore in reach, the sea is below me."
**Effort:** M — server-side data is already there; aggregation logic is new.

---

## P3 — Operational quality of life

### P3-A: Document `final_state` schema convention

**File:** `docs/cognitive-agent-integration.md`
**Current state:** Paracosm explicitly does not interpret the `final_state` blob — it's opaque from the world's perspective.
**Ask:** Add a "recommended schema" section so multiple cognitive architectures can write compatible diamond contents. Suggested wrapper:
```
{ schema: "<architecture-id>.v1",
  encoded_at: <world_time>,
  encoded_at_wall: <unix_ts>,
  entity_id: <string>,
  version: <string>,
  body: <opaque per-architecture blob> }
```
Then if a future "diamond reader" tool emerges (in any project), it can dispatch on `schema` field. KAINE would publish `kaine.kosmos.v1`.
**Why:** Encourages cross-architecture interop on diamond contents without prescribing format.
**Effort:** XS — pure doc change.

---

## Notes for the Paracosm agent

- KAINE's `Kosmos` module will speak the documented protocol as it exists today; it does not rely on any of these asks landing first. P0 items make embodiment *useful*; P1 makes it *socially aware*; P2 makes it *reproductive / spatial*; P3 makes it *operationally clean*.
- Every ask is strictly additive — none break existing reference clients like `scripts/example_cognitive_agent.py`.
- If you want a single bridge frame shape per ask before implementing, the cognitive-agent-integration guide is the authoritative place to land it; Kosmos will track that doc as the source of truth.
