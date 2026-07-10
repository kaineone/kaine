> ARCHIVED 2026-07-10: implemented — Mundus is a body-agnostic embodiment control plane with pluggable adapters (25/25 tasks).

# Refactor Mundus into a body-agnostic embodiment control plane with pluggable adapters

## Why

The paper now describes Mundus as **"a body-agnostic control surface rather than a
binding to any one platform… intended to drive an avatar in an immersive virtual
world, a physical robotic body, or another effector platform, each reached through a
small local adapter that translates between the bus and the body's native
interface"** (§3.4.6). That is an architecture-level claim about what the module *is*.

The code does not yet match it. `kaine/modules/mundus/module.py` opens *"embodies a
KAINE entity in a reference-body grid via the wire shim"*: the module owns the TCP server
itself, and `bridge.py` hardcodes the reference-body MessagePack wire protocol, the
reference-body action verbs, and the reference-body feed-kind→event map as module constants. Adding
any other body — a different world, a robot, a VR rig — means forking the module.
So Mundus today is a **single-platform connector wearing a body-agnostic name**; the
`reference-connector` change (built, but never archived) is what it actually implements.

This is now the load-bearing gap, not a cosmetic one, because the operator's stated
direction is to **drop the reference-body platform entirely and rebuild the paracosm around
VR-style body controls** (undecided in detail, but committed in direction). A
body-agnostic seam is exactly what makes that transition cheap:

- With the seam, dropping the reference body later is a one-file deletion of its adapter, not a
  module rewrite; the entity's perception/action contract with the workspace is
  untouched.
- **VR-style body controls are continuous** (per-tick graded setpoints), which
  converges with the paper's planned continuous control surface and the already-drafted
  `intuitive-embodiment-control-surface` change. If the seam's capability descriptor
  carries **both** symbolic verbs (today's reference body) **and** continuous channels
  (tomorrow's VR), the future VR/paracosm adapter and the continuous-surface change both
  drop in without touching the core again.

### The design line we hold: generalize the seam, preserve today's behavior

This is a **refactor for extensibility, not a behavior change** (per no-cheap-fixes:
do it right, at the architecture, not a symptom patch). The one working body today is
the reference adapter path; ripping it out now would leave the architecture with zero
embodiment while the VR direction is still undecided. So the reference-body bridge is moved
**behind** the new seam as the first, explicitly *transitional* reference adapter, its
wire protocol and runtime behavior bit-for-bit preserved and its existing tests kept
green. What changes is where the platform specifics live, not what they do.

## What Changes (design-only scope)

**This is a DESIGN-ONLY change.** It ships no behaviour code — only the OpenSpec
artifacts (this proposal, `design.md`, `tasks.md`, and one spec delta). Snippets in
`design.md` are illustrative. Implementation is a later, separately-approved change,
and MUST NOT boot an entity (design-first, per the OpenSpec-rigor and
minimise-entity-boots conventions).

The designed capability is a **body-agnostic embodiment control plane**:

- **An `EmbodimentAdapter` contract.** A small local protocol every body implements:
  open/close lifecycle, a perception stream that yields feed frames tagged by `kind`,
  an `apply_action(family, **params)` sink, and a **capability descriptor** the adapter
  declares — its action vocabulary (symbolic families and/or continuous channels), its
  feed-kind→(bus event, baseline salience) map, and each family's default exposure. The
  core reads the descriptor instead of importing any platform's constants.
- **A body-agnostic Mundus core.** The module keeps everything that is *not*
  platform-specific and drives it off the descriptor: the two-layer enable gate (config
  flag + `KAINE_MUNDUS_OPERATOR_APPROVED`), per-family exposure gating, the
  `locus == "virtual"` action gate, `intent.avatar.*` intent routing, the speech mirror,
  salience bumps, and the zero-raw-sense-data stripping (rendered frame buffers never
  reach the bus). None of this references the reference body, the wire shim, or any wire protocol.
- **The reference adapter as the first (transitional) adapter.** The current TCP
  server + length-prefixed-MessagePack bridge + reference-body verb/feed tables move into a
  `reference` adapter implementing the contract. Wire protocol unchanged; behavior
  preserved; existing tests kept green. It is marked transitional so its later removal is
  a bounded, expected operation.
- **Continuous channels in the descriptor from day one.** The descriptor can express
  clamped continuous setpoints (e.g. `drive`, `yaw_rate`, `gaze_yaw`, `gaze_pitch`,
  `interact`) alongside symbolic families, so the paper's continuous surface and a future
  VR body are expressible against the same seam without another core change. This change
  only *provides the shape*; wiring a continuous producer is
  `intuitive-embodiment-control-surface`'s job.
- **Adapter selection in config.** `[mundus].adapter = "reference"` (default), with
  adapter-specific settings nested under the adapter, replacing the reference-body-only keys
  that currently sit flat in `[mundus]`.

## Impact

- **Affected spec capability:**
  - `embodiment-control-plane` (ADDED, new capability): the adapter contract and
    capability descriptor; the body-agnostic core and its gating/locus/zero-persistence
    invariants; the reference adapter as a behavior-preserving transitional implementation;
    continuous-channel support in the descriptor; config adapter selection. This
    capability **supersedes** the embodiment requirements drafted in `reference-connector`
    (`reference-body-embodiment`, `world-action-intents`, `inbound-world-safety`) by absorbing
    them into a platform-independent form; those become the reference adapter's conformance
    to this contract.
- **Supersedes / re-scopes sibling changes (design housekeeping, no code):**
  - `reference-connector` — its Mundus becomes *the reference adapter behind this seam*,
    not the module itself. To be archived or annotated as superseded on approval.
  - `paracosm-connector` — its separate `Kosmos` module is folded into the adapter
    model: a future paracosm body is a **Mundus adapter**, not a sibling module (the
    operator confirmed this fold). The old sibling-module design is retired.
  - `intuitive-embodiment-control-surface` — unchanged in intent; its continuous surface
    becomes an adapter capability riding this seam. Its stated dependency on
    `reference-connector` re-points to this change plus whichever adapter is live.
- **Touch points for the future implementer** (design names them; no code here):
  `kaine/modules/mundus/module.py` (core, de-platformed), `kaine/modules/mundus/bridge.py`
  (moves under an `adapters/reference.py` implementation), a new
  `kaine/modules/mundus/adapter.py` (the protocol + descriptor), `kaine/boot.py` (adapter
  factory / selection), and the `[mundus]` block of `config/kaine.toml` (nest
  adapter-specific keys under `[mundus.reference]`).
- **Explicitly NOT touched:** the workspace/bus/cycle contracts; `perception_state`
  locus arbitration (reused, the core keeps gating on it); Volition and the
  `intent.avatar.*` family; the welfare/observer path; and — critically — the reference-body
  path's observable behavior, which this change preserves.
- **Explicitly NOT in scope:** designing the VR / rebuilt-paracosm adapter itself (the
  operator has not decided its shape), and wiring any continuous motor producer (that is
  `intuitive-embodiment-control-surface`). This change delivers only the seam and the
  behavior-preserving reference-body refactor.
