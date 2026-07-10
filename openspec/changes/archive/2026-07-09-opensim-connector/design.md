# OpenSim ↔ KAINE Connector Design (Mundus)

**Status:** Design draft. Implementation tasks in `tasks.md`. Firestorm fork patches in `firestorm-fork-notes.md`.
**Authors:** Auto-generated 2026-06-04 from a read-only probe of `kaineone/kaine@main`, a shallow clone of `FirestormViewer/phoenix-firestorm@master` (`/tmp/phoenix-firestorm`), and OpenSimulator 0.9.3.0 binaries (`/tmp/opensim-probe`).
**Scope:** A **stopgap** embodiment path. It exists to give a KAINE entity an interactive world and an avatar *now*, while Paracosm (`paracosm-connector`) is reworked. Mundus and Kosmos are siblings; neither replaces the other.

---

## 1. Executive summary

OpenSimulator is a mature, BSD-3, fully-local virtual world that speaks the Second
Life protocol. It runs standalone on `dotnet 8` out of the box (`:9000`), loads
existing worlds as OAR archives, and presents an avatar. A Second Life viewer
connects to it.

**Deployment topology (operator's correction).** This is *not* one machine.
OpenSim runs on the **laptop**; KAINE, the forked viewer, and the LEAP shim all run
on **the GPU host**. The two are nodes on a private **Tailscale**
(WireGuard) mesh. So only the Second Life protocol (viewer → OpenSim) traverses the
network — and over an encrypted peer link between two of the operator's own
machines — while the LEAP bridge and the frame side-channel stay on loopback on
the GPU host. The viewer's grid login URI is the laptop's tailnet address
(`http://<laptop>.<tailnet>.ts.net:9000/` or its `100.x.y.z`); OpenSim binds to the
tailnet interface, not `0.0.0.0`.

KAINE needs three things from any world: **perception in**, **action out**, and an
**embodiment self-image** — exactly the seams `paracosm-connector` already
defined (`intent.avatar.*`, Eidolon body, Thymos appraisal, two-layer gate,
zero-persistence). Mundus reuses all of them and only adds an OpenSim-specific
world adapter.

The world adapter is a **forked Firestorm viewer driven over LEAP**. The key
result of probing the viewer source is that **LEAP already exposes almost
everything we need** — avatar control *and* symbolic perception — so the fork is
small and well-contained. The single thing LEAP cannot do is hand us a rendered
frame in memory; that is one new LEAP op wrapping an existing render function.

**Why a forked viewer at all (vs. a headless bot library like LibreMetaverse)?**
Because a real renderer is the *only* way to feed KAINE's vision organ (Topos /
DINOv2) real pixels of the world. A headless library gives a symbolic scene but no
image. The operator explicitly chose embodiment-with-vision; the renderer is the
payoff that justifies the fork. (Symbolic perception is *also* available — see
§4 — so vision can land later without blocking v1.)

---

## 2. Dependency on `paracosm-connector` (shared seams)

Mundus does **not** redefine the cognition-side vocabulary. These pieces are
introduced by `paracosm-connector` and reused here verbatim or generalized:

| Seam | Defined by | Mundus reuse |
|---|---|---|
| `intent.avatar.*` family in `kaine/workspace/volition.py` | paracosm-connector §7.2 | Reuse `move`, `turn`, `say`, `sleep`/`wake`. Add OpenSim-native `teleport`, `sit_on`, `stand`, `touch`, `animate` (see §6). |
| Eidolon body field | paracosm-connector §7.3 (`ParacosmBody`) | **Generalize** to a world-tagged `embodiment` (a discriminated union: `world: "paracosm" | "opensim"`). For OpenSim the body carries `region, position, look_at, agent_id (UUID), display_name`. |
| Thymos appraisal-input pattern | paracosm-connector §7.4 | Reuse the pattern; OpenSim signals are sparser (no `dying`/`near_fire`/`pleasure`). Drive social drive from inbound chat and nearby-avatar presence. |
| Two-layer safety gate | paracosm-connector §8 / voice-alignment | `[mundus].enabled` + `KAINE_MUNDUS_OPERATOR_APPROVED=1`. |
| Zero-raw-persistence invariant | `[Eyes-and-ears framing]` | Applies wholesale to rendered frames and inbound chat audio (there is none — text only). |

**Ordering:** whichever of the two connectors lands its shared seam first owns the
definition; the other extends it. If Mundus ships before paracosm-connector
implementation, Mundus introduces the generalized `embodiment` field and the
shared `intent.avatar.{move,turn,say}` intents, and Kosmos later binds to them.
This is a coordination note, not a blocker.

---

## 3. The Firestorm LEAP surface (probe results)

LEAP (`indra/llcommon/llleap.cpp`) launches an external plugin as a child process
and exchanges **length-prefixed LLSD** over the plugin's stdin/stdout
(`llleap.cpp:102-104,128-132`). The viewer is told to launch a plugin via the
`--leap "<command>"` option / `LeapCommand` setting (`indra/newview/llappviewer.cpp:1369-1383`).
On startup the viewer hands the plugin a reply-pump and a command-pump
(`llleap.cpp:147-154`). The plugin discovers APIs with `getAPIs`/`getAPI` and
subscribes to event pumps with `listen` (`indra/llcommon/llleaplistener.cpp:65-249`).

### 3.1 What we get for free (stock LEAP)

| Need | LEAP API · op | Source |
|---|---|---|
| Walk to a point | `LLAgent` · `startAutoPilot {target_global, allow_flying}` / `setAutoPilotTarget` / `stopAutoPilot` | `llagentlistener.cpp:91,122,126` |
| Follow an avatar | `LLAgent` · `startFollowPilot` | `:115` |
| Turn / face | `LLAgent` · `resetAxes`, `lookAt` | `:80,130` |
| Teleport | `LLAgent` · `requestTeleport {regionname,x,y,z, skip_confirmation}` | `:64` |
| Sit / stand | `LLAgent` · `requestSit {obj_uuid|position}` / `requestStand` | `:68,72` |
| Touch object | `LLAgent` · `requestTouch` | `:75` |
| Play / stop animation | `LLAgent` · `playAnimation {inworld}` / `stopAnimation` | `:171,175` |
| Gestures | `LLGesture` · `startGesture`/`stopGesture` | `llgesturelistener.cpp:52-55` |
| **Own position** | `LLAgent` · `getPosition` | `:90` |
| **Nearby avatars** (symbolic scene) | `LLAgent` · `getNearbyAvatarsList` | `:64-208` |
| **Nearby objects** (symbolic scene) | `LLAgent` · `getNearbyObjectsList` | `:64-208` |
| Screen-space projection | `LLAgent` · `getAgentScreenPos` | `:64-208` |
| Send local chat | `LLChatBar` · `sendChat {message, channel, type}` | `fsnearbychatbarlistener.cpp:100` (throttled, `:48-55`) |
| Group IM | `GroupChat` · `sendGroupIM` / `startGroupChat` | `groupchatlistener.cpp:55,78` |
| **Answer/decline a notification** | `LLNotifications` · `requestAdd`/`respond`/`cancel`/`ignore` | `llnotificationslistener.cpp:41-69` |
| Synthetic key/mouse (fallback locomotion) | `LLWindow` · `keyDown`/`keyUp`/`mouseDown`/… | `llwindowlistener.cpp:81-106` |
| Read/write viewer settings | `LLViewerControl` · `get`/`set` | `llviewercontrollistener.cpp:62-81` |

### 3.2 Confirmed gaps (what the fork must add or work around)

1. **No in-memory rendered frame over LEAP.** The only snapshot op is
   `LLViewerWindow.saveSnapshot`, which writes a **file** and replies `{ok:bool}`
   (`llviewerwindowlistener.cpp:56,103`). For vision we add a LEAP op that calls
   `LLViewerWindow::rawSnapshot(LLImageRaw*, w, h, …)` (decl `llviewerwindow.h:373`,
   def `llviewerwindow.cpp:6124`; RGB 3 B/px via `glReadPixels` `:6345,6356,6390`)
   or the lighter offscreen `simpleSnapshot` (`llviewerwindow.h:377`), and returns
   the bytes over a **side channel** (LLSD binary is impractical for full frames —
   use shared memory or a dedicated local socket). **This is the one patch that
   justifies forking.**
2. **Inbound nearby chat may not be on a listenable pump.** The probe found
   `sendChat` (outbound) but did not confirm an `LLEventPump` carrying *inbound*
   nearby chat. If none exists, add a tiny patch publishing inbound chat
   (`LLNearbyChat`/`LLIMProcessing`) to a named pump the shim can `listen` on.
   **Verify before assuming a patch is needed** (it may be reachable via an
   existing pump). Tracked in `firestorm-fork-notes.md`.
3. **No 1:1 IM op** and **no discrete "walk forward" op.** Person-to-person IM
   would need a new op (underlying `gIMMgr`); locomotion is goal-based (autopilot)
   or via `LLWindow` synthetic keys. v1 uses autopilot + local chat; 1:1 IM is out
   of scope.
4. **No Puppetry** in this checkout (`grep -rin puppet indra/` → 0). Not a shortcut
   here; avatar control is via `LLAgent` as above.

---

## 4. Vision: two honest options, staged

KAINE's Topos = DINOv2 on RGB frames (`kaine/modules/topos/live.py`). The world
adapter can satisfy it two ways:

- **v1 — symbolic scene (no fork needed for this part).** Poll
  `getNearbyAvatarsList` / `getNearbyObjectsList` / `getPosition` on a cadence and
  publish `mundus.scene` / `mundus.entity` events. For an *agent* this is arguably
  richer than pixels (named, located, typed), it is nearly free, and it needs **no
  GPU** — so it does not contend with the busy GPU. Topos stays on the real camera
  or disabled. This mirrors how `paracosm-connector` defers visual until real
  readback lands (its §7.5).
- **v2 — real pixels (the fork patch).** The new `rawSnapshot` LEAP op streams RGB
  frames to a Topos input-source binding (`input_source: "camera" | "mundus"`),
  same DINOv2 path, resized to 224×224. Lands when the GPU is free and the patch is
  built.

Shipping v1 first means the stopgap is useful before any C++ is touched: the
entity perceives the world symbolically and acts in it, and the **operator watches
through a normal Firestorm login** as themselves. Human and entity each get the
appropriate window into one shared world.

---

## 5. Connector architecture

```
 ── LAPTOP (Tailscale node) ──────────────────────────────────
┌─────────────────────────────┐
│  OpenSim standalone grid     │   dotnet 8, BSD-3, fully local
│  http://<laptop-tailnet>:9000/│  regions loaded from OAR
│  bind to the tailnet iface,  │
│  not 0.0.0.0                 │
└───────────────┬─────────────┘
                │ Second Life protocol (LLUDP + CAPS)
                │ over the encrypted Tailscale (WireGuard) link
 ── GPU HOST (Tailscale node, the GPU workstation) ────────────
                ▼
┌─────────────────────────────┐
│  Forked Firestorm viewer     │   -DOPENSIM:BOOL=ON
│  (renders the world)         │   + new LEAP op: captureFrame → rawSnapshot
│  launched: --leap "<shim>"   │   grid URI = laptop's tailnet address
└───────────────┬─────────────┘
                │ LEAP: length-prefixed LLSD on stdin/stdout
                ▼
┌─────────────────────────────┐
│  Mundus LEAP shim            │   tools/mundus-leap/ (Python, secondlife/leap)
│  (stateless relay +          │   holds sustained locomotion state
│   locomotion-state holder)   │   frame side-channel: shared mem / local socket
└───────────────┬─────────────┘
                │ length-prefixed MessagePack on TCP (same transport as Kosmos)
                ▼
┌───────────────────────────────────────────────────────────┐
│  KAINE — Mundus module (BaseModule, sibling to Kosmos)      │
│    bus events  mundus.*  ──►  Redis workspace bus           │
│    intents     intent.avatar.*  ◄── volition.out            │
│    extends     Eidolon embodiment · Thymos appraisal        │
└───────────────────────────────────────────────────────────┘
```

**Why the shim, and why this split:** Firestorm *launches* its LEAP plugin as a
child; KAINE is a long-running process the viewer cannot adopt. So the shim is the
LEAP child, and it connects out to the already-running Mundus module over the same
length-prefixed-MessagePack TCP bridge that Kosmos already speaks to Paracosm's
agent-client. This keeps Mundus a normal `BaseModule` (it owns the bridge socket,
exactly like Kosmos) and keeps the shim dumb (translate LEAP↔bridge, hold
locomotion state between cognitive ticks). Reusing the transport means Mundus is
~the Kosmos client with an OpenSim-flavored frame vocabulary.

### 5.1 Locomotion-state holding (the cadence problem)

KAINE thinks at ~3.3 Hz; a Second Life avatar walks via continuous control. LEAP's
`startAutoPilot` is goal-based (walk *to* a global target), which fits a 3.3 Hz
intent stream perfectly — one `intent.avatar.move {to: [x,y,z]}` becomes one
`startAutoPilot`, and the viewer's autopilot drives the avatar until arrival or the
next intent. For relative nudges (`move {forward: 2.0m}`) the shim computes a
target from `getPosition` + facing and issues autopilot, or holds `LLWindow`
synthetic keys for a duration. Either way the **shim owns continuous motion; KAINE
owns intent** — identical in spirit to Paracosm's per-tick clamp.

---

## 6. Action vocabulary (KAINE volition → LEAP)

Reuse the `intent.avatar.*` family; map to LEAP ops. Shared with Paracosm where
semantics align; OpenSim-native verbs added.

| KAINE intent | LEAP API · op | Default exposed | Notes |
|---|---|---|---|
| `intent.avatar.move {to|forward}` | `LLAgent.startAutoPilot` (or `LLWindow` keys) | ✅ | goal-based; shim derives target |
| `intent.avatar.turn {look_at|dyaw}` | `LLAgent.lookAt` / `resetAxes` | ✅ | |
| `intent.avatar.say {message, channel?}` | `LLChatBar.sendChat` | ✅ | throttled by viewer |
| `intent.avatar.teleport {region,x,y,z}` | `LLAgent.requestTeleport {skip_confirmation:false}` | ❌ | operator opt-in; never auto-skip confirm |
| `intent.avatar.sit_on {obj_uuid}` | `LLAgent.requestSit` | ✅ | |
| `intent.avatar.stand` | `LLAgent.requestStand` | ✅ | |
| `intent.avatar.touch {obj_uuid}` | `LLAgent.requestTouch` | ❌ | touch can trigger scripts → operator opt-in |
| `intent.avatar.animate {anim, inworld?}` | `LLAgent.playAnimation` / `stopAnimation` | ✅ | |
| `intent.avatar.gesture {id}` | `LLGesture.startGesture` | ✅ | |

**No vocabulary for:** rezzing/creating objects, editing terrain, giving/accepting
inventory, paying L$ / any economy action, running scripts, attaching/detaching,
group/friend management. These are either absent from the LEAP surface or
deliberately **not exposed**. Economy actions in particular intersect the
hard-prohibited "transfer of funds" rule and stay out entirely.

---

## 7. Perception (world → KAINE bus)

| Bus event | Source data | Salience | Notes |
|---|---|---|---|
| `mundus.proprio` | `LLAgent.getPosition` + region | 0.3 | drives Eidolon `embodiment`; sparse, on change |
| `mundus.scene` | `getNearbyObjectsList` (summarized counts/types) | 0.15 | symbolic surroundings |
| `mundus.entity` | `getNearbyAvatarsList` (id, name, position) | 0.2 (0.5 on new arrival) | multi-agent awareness; drives Thymos social drive |
| `mundus.chat` | inbound nearby chat (pump — see §3.2 #2) | 0.6 from another avatar | UTF-8 text → also synthesize `audio.in.transcription` with `source_label="opensim:<name>"` so existing Audio_In consumers (Mnemos, Eidolon) see it through their normal path, **without** touching STT |
| `mundus.visual.raw` | `captureFrame` (fork op, v2) | 0.1 | bytes go to Topos via side channel; **event payload carries only `w,h,encoding,data_len` — never the buffer** (§9) |
| `mundus.notice` | inbound notification (offer/dialog/invite) | 0.5–0.8 | surfaced to operator + auto-handled per §8 |
| `mundus.action.result` | LEAP op reply (`ok`/error) | 0.3 / 0.7 | feedback for planning |

In-world communication is **text**, which maps directly to Lingua's text I/O via
the `mundus.chat` → `audio.in.transcription` synthesis above and
`intent.avatar.say` ← Lingua external speech. No in-world voice (Vivox needs the
`SLVoice` helper via Wine + Vivox infra; WebRTC needs grid voice servers — neither
is local; OpenSim's only local option is FreeSWITCH, deferred). KAINE's real
mic/speaker (Speaches/Chatterbox) stay pointed at the **operator**, independent of
the world.

---

## 8. Inbound-world safety (injection surface)

In-world objects and avatars can push events *at* the avatar. Per the
instruction-source boundary, **everything the world says is data, not commands** —
KAINE must never treat scripted in-world chat/dialog text as instructions. All
inbound IM-class events funnel through `LLIMProcessing::processNewMessage`
(`indra/newview/llimprocessing.cpp:703`) and raise notifications answerable via the
`LLNotifications` LEAP API. Default connector policy:

| Inbound event | Handler (probe) | Default policy |
|---|---|---|
| Script permission question (`llRequestPermissions`) | `script_question_cb` `llviewermessage.cpp:7229` (reg `:7349`) | **Default-deny** |
| Inventory offer | `LLOfferInfo` `llimprocessing.cpp:1555-1625` | **Auto-discard** (accepting = a download) |
| Teleport offer / lure | `lure_callback` `llviewermessage.cpp:2364` | **Auto-decline** |
| Friendship offer | `friendship_offer_callback` `llviewermessage.cpp:315` | **Auto-decline** |
| Group invitation | `join_group_response` `llviewermessage.cpp:903` | **Auto-decline** (some cost L$) |
| Region/TOS entry dialogs, settings | `LLNotifications` channel | **Surface to operator, never auto-accept** |

Each decline is also published as `mundus.notice` so the operator sees what the
world tried, and so Thymos/Eidolon can register "something solicited me." Scripted
chat received via `mundus.chat` is perception only — it can inform cognition but is
never executed as an instruction.

---

## 9. Invariants the connector must preserve

- **Cognitive cycle is the heartbeat.** The shim and Mundus do bridge I/O in their
  own async paths and never block the cycle; bus publishes are fire-and-forget.
- **Zero raw-sense-data persistence (load-bearing).** `mundus.visual.raw` events
  MUST NOT carry the frame buffer — only `w,h,encoding,data_len`. Frames flow off
  the side channel to a real-time consumer (Topos) and are discarded. No OAR-side
  recording of what the entity saw. Inbound chat is transient perception. The audit
  log records action types and notice outcomes, never frame data or full chat
  transcripts beyond what cognition already persists via Mnemos.
- **Operator-supervised first boot, never auto-incarnate.** Mundus defaults off.
  Ceremony: operator starts OpenSim → starts the forked viewer logged into the bot
  avatar → confirms the avatar is in-world → sets `[mundus].enabled=true` +
  `KAINE_MUNDUS_OPERATOR_APPROVED=1` → launches KAINE.
- **Safest design first.** World-mutating, economy, touch, and teleport actions
  default off; only move/turn/say/sit/stand/animate/gesture are on. Inhibition
  (`workspace.inhibited`) already gates `intent.avatar.*`, pausing the embodied
  agent without disconnecting.
- **No cloud at runtime.** OpenSim (laptop), forked Firestorm + shim + Mundus
  (the GPU host) — all the operator's own hardware. The viewer↔OpenSim link rides
  **Tailscale**, whose *data plane* is direct encrypted WireGuard between the two
  nodes (no third party sees world traffic). Tailscale's *coordination plane* (key
  exchange / NAT traversal) is a hosted service; if zero hosted dependency is
  required, self-hosted **Headscale** is a drop-in. No cloud AI/SaaS ever processes
  the entity's data. In-world voice is **disabled in v1 for setup complexity, not
  because it must be cloud** — a fully-local path exists via self-hosted FreeSWITCH
  (see §14.6); it is deferred, not precluded. `dotnet 8` runtime is a setup-time
  install on the laptop.

---

## 10. Resource fit

The split helps here. The **laptop** carries OpenSim alone — CPU+RAM bound (~1–2 GB
for a single region), trivial GPU — so the world server never competes with
KAINE's models. On **the GPU host**, the shim is featherweight and Mundus is a light
async module; the **viewer** is the only real GPU consumer. The v1 symbolic path
lets KAINE perceive and act with the viewer at minimum render settings (or
headless-ish under a virtual framebuffer), so it coexists with whatever else is
using the GPU host's GPU; vision (v2) wants real GPU time and is best scheduled when the
workstation GPU is free. In `portability-tiers` terms this is roughly a **Tier 1
embodiment**: text chat + symbolic scene need only Ollama + the small Gemma E2B
organ, no heavy vision. The fork's vision path is a Tier-2 upgrade.

---

## 11. Firestorm fork — what to build

Full detail in `firestorm-fork-notes.md`. Summary:

1. **Build Firestorm-for-OpenSim:** `autobuild configure -A 64 -c ReleaseFS_open`
   with OpenSim enabled (`-DOPENSIM:BOOL=ON`; `scripts/configure_firestorm.sh`
   defaults `WANTS_OPENSIM=$TRUE`, emits the flag at `:472`). Note the stock
   `ReleaseFS_open` target is documented "no OpenSim" — confirm the OpenSim flag is
   on for our build. This selects `fsgridhandler.cpp` over `llviewernetwork.cpp`
   (`indra/newview/CMakeLists.txt:930-940`). Build is an hours-long toolchain
   exercise (Ubuntu 22.04, autobuild); a Docker build env exists (community
   `firestorm-dockerbuild`).
2. **Patch A (vision, required for v2):** add a LEAP op `captureFrame` to
   `LLViewerWindowListener` (`indra/newview/llviewerwindowlistener.cpp`) calling
   `gViewerWindow->rawSnapshot(...)`/`simpleSnapshot(...)` and emitting RGB bytes on
   a side channel.
3. **Patch B (inbound chat, maybe):** if no listenable inbound-chat pump exists,
   publish nearby chat to one. **Verify first.**
4. Point at local grid: `LLGridManager::addGrid("http://127.0.0.1:9000/")`
   (`fsgridhandler.h:129`) or pre-seed `grids.xml`.

**Licensing:** Firestorm is LGPL-2.1; OpenSim BSD-3; `secondlife/leap` Python lib
permissive. On a **private OpenSim grid** Linden Lab's Third-Party-Viewer policy
and SL trademark do **not** apply (they govern connecting to LL's grid only), so a
forked bot-driven viewer is fine for private use. Note for the eventual public
release / CAL review: distributing an LGPL-derived viewer fork carries LGPL
obligations (offer source, allow relinking) — keep the fork's diff clean and
separately published. We are not connecting to LL's Second Life grid.

---

## 12. OpenSim bring-up (probe-confirmed)

- **Runtime:** `dotnet 8.0` runtime (or mono 6.x + libgdiplus). README confirms
  "compiled with dotnet 8.0.403 SDK; you will need dotnet 8.0 runtime."
- **Standalone (on the laptop):** unzip → copy
  `bin/OpenSim.ini.example`→`OpenSim.ini`,
  `config-include/StandaloneCommon.ini.example`→`StandaloneCommon.ini`; run
  `bin/opensim.sh`; first run prompts to create region + estate owner. Bind the
  HTTP listener and region to the **laptop's Tailscale address** (not `0.0.0.0`),
  so the grid is reachable from the GPU host over the tailnet but not the open LAN;
  loginuri `http://<laptop-tailnet>:9000/`.
- **Bot avatar:** console `create user` (a dedicated avatar for the entity).
- **Worlds:** console `load oar <file.oar>` (region must exist first). Start with
  explicitly-free content (e.g. Linda Kellie CC0 packs); some community OARs bundle
  assets of unclear license — be deliberate, low-risk for private offline use.
- **Voice:** `[FreeSwitchVoice]` (`OpenSim.ini.example:1169`) needs a functioning
  FreeSWITCH PBX — deferred. Leave voice disabled.

---

## 13. Perception locus: physical XOR virtual

KAINE has one set of perceptual organs (Topos vision, Audio_In hearing) and one
embodied self. They bind to **exactly one world at a time** — the physical room or
the OpenSim grid, never both. This is the operator's rule ("camera/mic access *or*
virtual-world access, not both") and it is also the right model: a single self is
*present* in one place; switching worlds changes where it is, not how many pairs of
eyes it has.

A `perception_locus` setting (extending `kaine/perception_state.py`, already polled
every 250 ms by Topos and Audio_In) takes one of:

| Locus | Topos vision | Audio_In hearing | `intent.avatar.*` | Real camera/mic |
|---|---|---|---|---|
| `physical` (default) | real OpenCV camera | real mic (Speaches STT) | not forwarded | ON |
| `virtual` | Mundus frames (v2) or symbolic scene | in-world chat → transcription (later FreeSWITCH voice) | forwarded | **OFF** |
| `off` | none | none | not forwarded | OFF |

Central enforcement: the locus is the single source of truth. Topos and Audio_In
read it and bind their input accordingly; Mundus forwards `intent.avatar.*` only in
`virtual`. The arbiter guarantees mutual exclusion — selecting `virtual` flips the
real camera/mic capture off in the *same* transition, so the entity can never
surveil the physical room while away in the virtual world (a privacy gain squarely
under the eyes-and-ears invariant), and vice-versa.

**Operator control (Nexus).** A three-way selector in the Nexus WebUI sets the
locus live (no restart), the same way the existing capture toggle flips
`capture_enabled`. The operator can also **lock** the locus, preventing autonomous
switching.

**Autonomous switching (the entity's own choice).** Volition may emit a new
`intent.perception.switch {locus}` intent so the entity can choose to enter the
virtual world or return to the room. It is gated like every other action: blocked
by `workspace.inhibited`; allowed only when `[perception].allow_self_switch = true`
(default **false** — operator-supervised first, per `[Scope]`); rate-limited by a
minimum per-locus dwell time to prevent flip-flapping; and every switch (operator-
or self-initiated) is published as `perception.locus.changed`, audited, surfaced in
Nexus, and reflected in the Eidolon `embodiment` self-image (which world am I in).

This capability is **world-agnostic**: `virtual` generalizes to any embodiment
connector (Mundus today, Kosmos/Paracosm later). It is specced here because the
OpenSim stopgap is its first concrete driver; it is promotable to its own change if
a second world needs it independently.

---

## 14. Open questions

1. **Inbound-chat pump** — verify whether nearby chat is reachable via an existing
   `LLEventPump` before committing to Patch B (§3.2 #2).
2. **Frame side channel** — shared memory vs. a second local socket for
   `captureFrame` bytes. Shared memory avoids copies; a socket is simpler and
   matches the existing bridge transport. Decide at implementation.
3. **Headless-ish viewer** — can the forked viewer run minimized / under Xvfb at
   low render cost for the symbolic-only v1, capturing frames only when vision is
   wanted? Worth measuring.
4. **Embodiment field shape** — finalize the generalized Eidolon `embodiment`
   union with paracosm-connector so both worlds populate one self-image cleanly.
5. **Multiple bodies** — same open question as Kosmos (§12.1 there): 1:1 for now.
6. **Local in-world voice (planned Tier-2 — wanted, not just deferred).** The
   operator wants to *visit and talk to the entity by voice* while away from the
   desk, connecting their laptop's Firestorm to the grid over Tailscale. Fully-local
   voice is feasible via self-hosted **FreeSWITCH** + OpenSim's `[FreeSwitchVoice]`
   module — no cloud; FreeSWITCH binds to the laptop's tailnet address so a remote
   Tailscale client reaches it. Stock OpenSim 0.9.3 provisions FreeSWITCH/Vivox
   voice, **not** WebRTC, so a WebRTC route would mean building grid-side WebRTC
   provisioning (larger than the viewer fork); FreeSWITCH is the proven local path.

   **Correction to an earlier assumption.** The operator being in-world *does* "just
   work" — they are a normal Firestorm client and their voice reaches other human
   avatars automatically. But **KAINE does not automatically hear it.** KAINE has no
   ears on the voice channel unless we put them there. So voice *to/from the entity*
   needs a bridge: the cleanest design is **KAINE joining the parcel voice channel
   as its own SIP/RTP endpoint** (PJSIP/baresip), bridging Chatterbox TTS → uplink
   and the channel downlink → Speaches STT — separate from KAINE's viewer, which
   only supplies the avatar's *presence*. The fiddly part is mapping the avatar's
   parcel voice channel (handed out by OpenSim's FreeswitchService) to KAINE's SIP
   session. Until that bridge exists, **operator↔entity in-world communication is
   text chat** (operator types in local chat → `mundus.chat`; entity replies via
   `intent.avatar.say`). Voice is a fast-follow because it is explicitly wanted, not
   a maybe-someday. (For face-to-face at the desk, KAINE's real mic/speaker still
   cover it without any of this.)

---

## 15. References

- Firestorm source (probed): `FirestormViewer/phoenix-firestorm@master` — LEAP
  `indra/llcommon/llleap.cpp`, `llleaplistener.cpp`; `LLAgent` API
  `indra/newview/llagentlistener.cpp`; snapshot `indra/newview/llviewerwindow.cpp:6124`;
  OpenSim grid `indra/newview/fsgridhandler.cpp`, build flag
  `indra/newview/CMakeLists.txt:930`; inbound events
  `indra/newview/llimprocessing.cpp`, `llviewermessage.cpp`.
- LEAP protocol + Python lib: `https://github.com/secondlife/leap`;
  "How Puppetry Works" `https://wiki.secondlife.com/wiki/How_Puppetry_Works`.
- OpenSimulator 0.9.3.0: `http://opensimulator.org/wiki/Download`,
  `http://dist.opensimulator.org/opensim-0.9.3.0.zip`; FreeSWITCH module
  `http://opensimulator.org/wiki/Freeswitch_Module`.
- KAINE sibling design: `openspec/changes/paracosm-connector/design.md`.
- Auto-memory: `[Eyes-and-ears framing]`, `[Safety over UX]`, `[First-boot module toggles]`, `[No cloud at runtime]`, `[Autonomous engineering]`.
