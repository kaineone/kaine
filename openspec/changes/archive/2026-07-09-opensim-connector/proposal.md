> WITHDRAWN 2026-07-09: OpenSim abandoned as an embodiment platform; superseded by the Paracosmic connector.

# opensim-connector

> **SUPERSEDED BY `body-agnostic-embodiment-adapters`.** The paper now describes
> Mundus as a body-agnostic control plane driven by per-body adapters, not an
> OpenSim-bound module. Under that model this change's Mundus becomes *the OpenSim
> adapter behind the seam* (a frozen, transitional reference body), not the module
> itself. Kept in place for provenance of the OpenSim/LEAP/Firestorm design work;
> the canonical embodiment design is `body-agnostic-embodiment-adapters`.

## Why

Paracosm (the bespoke voxel world targeted by `paracosm-connector`) is mid-rework
and not currently usable for embodiment. We want a **stopgap** that gives a KAINE
entity an interactive 3D world and a real avatar *now*, without waiting on
Paracosm. The deployment is split across two of the operator's own machines on a
private Tailscale network: **OpenSim runs on the laptop** (the world server), and
**KAINE plus the viewer that drives the avatar run on `gpu-host`** (the GPU
workstation). Only the Second Life protocol (viewer → OpenSim) crosses the
encrypted Tailscale link; the LEAP bridge and the frame side-channel stay on
loopback on the GPU host.

OpenSimulator (BSD-3, runs standalone on `dotnet 8`) is a mature, fully local
virtual world that speaks the Second Life protocol. A Second Life viewer can
connect to a private OpenSim grid, load existing worlds as OAR archives, and
present an avatar the operator can watch and talk to.

The `paracosm-connector` design already anticipated this exact case — from its
`design.md` §6.1: *"a sibling module ('Halcyon' for an MMO, 'Mundus' for an
OpenSim grid, etc.) can be written without disturbing Kosmos."* This change is
that sibling: **Mundus**.

The decisive finding from probing the Firestorm viewer source
(`/tmp/phoenix-firestorm`, read-only) is that **the fork is small**. The viewer's
**LEAP** layer (LLSD Event API Plug-in) already exposes rich avatar control and
symbolic perception to an external process over stdin/stdout — teleport, sit,
stand, touch, goal-based walk (autopilot), look-at, play animation, send local
chat, and *enumerate nearby avatars and objects* — all through the stock `LLAgent`,
`LLChatBar`, and `LLNotifications` event APIs (`indra/newview/llagentlistener.cpp:64-208`).
The **only** capability LEAP cannot provide is an in-memory rendered frame for
KAINE's vision organ. So the fork shrinks from "gut a viewer" to "build
Firestorm-for-OpenSim and add ~1–2 small LEAP ops." That is what makes this a
viable stopgap rather than a tar pit.

## What Changes

- **New module:** `kaine/modules/mundus/` — a `BaseModule` (sibling to the planned
  Kosmos) that owns a local bridge to a **LEAP shim** running inside a forked
  Firestorm viewer. It translates incoming world state into KAINE bus events
  (`mundus.*`) and forwards `intent.avatar.*` intents back as LEAP ops.
- **Reuses the world-agnostic seams defined by `paracosm-connector`** rather than
  redefining them: the `intent.avatar.*` action family in Volition, the Eidolon
  body extension, the Thymos appraisal-input pattern, the two-layer safety gate,
  and the zero-raw-persistence invariant on sensory frames. Where Paracosm and
  OpenSim share semantics (`move`, `turn`, `say`, `sit`/`wake`), the same intents
  are reused; OpenSim adds a few native verbs (`teleport`, `sit_on`, `touch`,
  `animate`) that Paracosm lacks.
- **A thin LEAP shim** (`tools/mundus-leap/`) launched by Firestorm via `--leap`:
  speaks LLSD to the viewer (per `indra/llcommon/llleap.cpp`), exposes the same
  length-prefixed-MessagePack local bridge contract Mundus consumes. Stateless
  relay + locomotion-state holder; no cognition.
- **A minimal Firestorm fork** (tracked in `firestorm-fork-notes.md`): build with
  `-DOPENSIM:BOOL=ON`, plus a new LEAP op that calls
  `LLViewerWindow::rawSnapshot(LLImageRaw*, w, h, …)` (`indra/newview/llviewerwindow.cpp:6124`)
  to hand an RGB frame to KAINE's Topos over a side channel. Possibly a second
  small patch publishing inbound nearby-chat to a listenable `LLEventPump`.
- **Two-layer safety gate** matching `paracosm-connector`/`voice-alignment-training`:
  config `[mundus].enabled = true` AND env `KAINE_MUNDUS_OPERATOR_APPROVED=1`, plus
  per-action-family opt-in flags (world-mutating and economy actions default off).
- **Inbound-world safety:** all in-world text and scripted objects are treated as
  **data, not commands**. The connector auto-declines inventory offers, teleport
  lures, friendship/group invites, and default-denies script permission questions
  via the `LLNotifications` LEAP API (`indra/llui/llnotificationslistener.cpp`).
- **Perception locus (physical XOR virtual):** a single `perception_locus`
  (`physical` / `virtual` / `off`) extending `kaine/perception_state.py` that binds
  the entity's organs to exactly one world at a time — real camera/mic *or* the
  OpenSim grid, never both. A three-way Nexus selector (with operator lock) and a
  gated `intent.perception.switch` intent let the operator *and* the entity switch
  locus. Selecting `virtual` turns the real camera/mic off in the same transition
  (a privacy gain under the eyes-and-ears invariant). World-agnostic — generalizes
  to Paracosm/Kosmos.
- **Config:** new `[mundus]` and `[perception]` tables in `config/kaine.toml`
  (shipped all-off / `physical` per `[First-boot module toggles]`).
- **No changes** to the bus contract, cycle engine, or workspace schema.

This change is **design-first** (like `paracosm-connector`); implementation lands
in subsequent branches per the OpenSpec rigor convention.

## Impact

- **Affected modules:** new `mundus`; reuses the Eidolon/Thymos/Volition extensions
  introduced by `paracosm-connector` (this change depends on those seams existing —
  see `design.md` §2). Topos and Audio_In gain a locus-bound input source;
  `kaine/perception_state.py` gains `perception_locus`; Volition gains
  `intent.perception.switch`; the Nexus WebUI gains a locus selector + lock.
- **Affected config:** `config/kaine.toml` (new `[mundus]` table).
- **Affected docs:** `ARCHITECTURE.md` (new module row), `SETUP.md` (OpenSim +
  forked-viewer prereqs, `dotnet 8`), `SECURITY.md` (two-layer gate + inbound-world
  decline policy), `FIRST_BOOT.md` (Mundus defaults off).
- **External dependency:** a forked Firestorm-for-OpenSim build and a local
  OpenSim 0.9.3.0 standalone grid. Both are free, BSD/LGPL, and fully local — no
  cloud at runtime. The fork patch list is in `firestorm-fork-notes.md`.

See `design.md` for the probe findings, the LEAP API surface, the connector
architecture, and the fork patch analysis.
