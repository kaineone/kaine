# paracosm-connector

> **SUPERSEDED BY `body-agnostic-embodiment-adapters`.** The paper's control-plane
> framing collapses the old "one sibling module per world" model (a separate
> `Kosmos` module here) into "one Mundus + per-body adapters." A future paracosm
> body is therefore a **Mundus adapter**, not its own module (operator-confirmed
> fold, 2026-07-05). Note also the operator's stated direction to drop the
> transitional reference body and rebuild the paracosm around VR-style continuous
> body controls — the eventual
> paracosm adapter targets that, not this Bevy-voxel bridge. Kept for provenance.

## Why

Paracosm (https://github.com/kaineone/Paracosm) is a virtual world being built
for embodied cognitive architectures: a Rust + Bevy headless voxel sim with
procedural terrain, celestial mechanics, weather, fire, lifecycle (mortality
+ memory diamonds + reproduction), and a per-agent client that bridges five
sensory feeds (proprio / temporal / intero / visual / audio) plus an action
channel to an external "cognitive agent" process over length-prefixed
MessagePack on raw TCP (default port `7780`).

A KAINE entity should be able to embody into a Paracosm avatar — receive its
proprioception, see what it sees, hear what it hears, and act on the world
through avatar primitives (move, turn, say, place, break, eat, mate, …) —
without either project being permanently coupled to the other. Paracosm is
designed to host any cognitive architecture; KAINE is designed to embody into
any interface, virtual or physical.

This change introduces a new KAINE module, **Kosmos**, that opens the
Paracosm cognitive-agent bridge, translates incoming sensory frames into
KAINE bus events, and forwards a new family of `intent.avatar.*` intents
back to Paracosm as action frames. It also catalogues the gaps on both sides
so the two repos can move forward in lockstep.

## What changes

- **New module:** `kaine/modules/kosmos/` — a `BaseModule` that runs an async
  TCP client against the Paracosm bridge, decodes the five feed kinds plus
  the death-sequence `shutdown` and forthcoming `event` / `entity_update`
  kinds, and publishes them as kaine bus events.
- **New event types** under `kosmos.*` and `intent.avatar.*` (see
  `design.md` §6 for the full table).
- **Volition extension:** new `INTENT_TYPES` entries for the avatar action
  family — proposed in `design.md` §7.2 — so `Volition.publish(intent)` can
  emit avatar intents without overloading `intent.act`. (Praxis effectors
  remain for local-machine side-effects.)
- **Eidolon extension:** a `paracosm_body` field on the self-model populated
  from `kosmos.proprio` — gives the entity its first real "I am embodied as
  agent_id=X at position=Y" sense.
- **Thymos integration:** consume `pleasure`, `dying`, eclipse / comet /
  shooting-star flags as appraisal inputs.
- **Two-layer safety gate** matching `voice-alignment-training`: config
  `[kosmos].enabled = true` AND env `KAINE_KOSMOS_OPERATOR_APPROVED=1`.
  Plus per-action-family opt-in flags (place / break / eat / mate default to
  `false`).
- **Config:** new `[kosmos]` table in `config/kaine.toml` (shipped all-off).
- **Operator doc:** `kaine/modules/kosmos/KOSMOS.md`.
- **No changes** to the underlying bus contract, cycle engine, or workspace
  schema — Kosmos publishes via the existing `BaseModule.publish` path.

This change is design-only at first; implementation lands in subsequent
branches per the OpenSpec rigor convention.

## Impact

- **Affected modules:** new `kosmos`; touch points in `eidolon`, `thymos`,
  optionally `topos` (when Paracosm's real visual feed lands).
- **Affected config:** `config/kaine.toml` (new `[kosmos]` table).
- **Affected docs:** `ARCHITECTURE.md` (new module row), `SETUP.md` (Paracosm
  connection prereqs), `SECURITY.md` (two-layer gate + per-action opt-ins),
  `FIRST_BOOT.md` (Kosmos defaults off).
- **Cross-project asks** for the Paracosm repo are listed in
  `paracosm-counterpart-asks.md` and should be opened as issues there.

See `design.md` for the comparison report, gap analysis, and connector
architecture.
