# Tasks — Body-agnostic embodiment control plane with pluggable adapters

> **Design-of-record only.** The operator asked to **plan, not implement.** These
> tasks are the future implementation roadmap; do not start them without a go, and
> **do not boot an entity**. Phases map to `design.md`. This change **supersedes**
> `reference-connector` (its Mundus becomes the reference adapter) and folds
> `paracosm-connector`'s Kosmos into the adapter model. It precedes and provides the
> seam for `intuitive-embodiment-control-surface`.

## W0 — Guardrails (read before starting)
- [x] 0.1 Decisions resolved (`design.md` §10): freeze the reference body, fix channels to
      `drive/yaw_rate/gaze_yaw/gaze_pitch/interact`, annotate supersession, build a stub.
- [x] 0.2 Re-read `design.md` §2/§6: the split is a **move + indirection**, not a
      rewrite; the reference-body path's observable behavior is preserved bit-for-bit.
- [x] 0.3 Confirm the module still ships inactive after the config restructure: the
      real off-switch is `[modules].mundus = false`; `[mundus].enabled` stays `true`
      (unchanged, harmless behind the module toggle + operator env gate).

## W1 — The adapter contract (`kaine/modules/mundus/adapter.py`)
- [x] 1.1 Define `EmbodimentAdapter` protocol: `capabilities()`, `open()`, `close()`,
      `feed()` (async iterator of `FeedFrame(kind, payload)`), `apply_action(family,
      params) -> bool`, `apply_setpoints(channels) -> bool`.
- [x] 1.2 Define `EmbodimentCapabilities` dataclass (name, transitional, feed_events,
      action_families, continuous_channels, raw_buffer_keys) and `FeedFrame`.
- [x] 1.3 Unit-test the descriptor is frozen/validated (no unknown families, salience
      in [0,1], continuous channel names non-empty when a continuous sink exists).

## W2 — De-platform the Mundus core (`kaine/modules/mundus/module.py`)
- [x] 2.1 Change `Mundus.__init__` to take an injected `adapter: EmbodimentAdapter`;
      drop `bridge_host`/`bridge_port`/`expose`/reference-body knowledge from the module.
- [x] 2.2 Drive feed→event mapping, exposure defaults, and raw-buffer stripping from
      `adapter.capabilities()` instead of `FEED_EVENT` / `ACTION_DEFAULT_EXPOSED`.
- [x] 2.3 Keep in the core: two-layer enable gate, `locus == "virtual"` gate,
      `intent.avatar.*` routing, speech mirror, salience bumps, cursor seeding,
      serialize/deserialize, and the never-block-the-cycle fire-and-forget publish.
- [x] 2.4 Route symbolic intents to `apply_action` and (future) continuous setpoints to
      `apply_setpoints`; clamp setpoints to declared ranges; gate continuous channels by
      a per-channel exposure map (default off) + locus.
- [x] 2.5 `initialize()` calls `adapter.open()` and pumps `adapter.feed()`; `shutdown()`
      calls `adapter.close()`; the core owns no socket.

## W3 — Reference adapter (`kaine/modules/mundus/adapters/reference.py`)
- [x] 3.1 Move the TCP `start_server` listener + single-connection "newest wins" here.
- [x] 3.2 Move `bridge.py`'s wire protocol under the adapter (or re-import it unchanged);
      implement `feed()` from inbound frames and `apply_action` as outbound action frames
      with `reqid`, exactly as today.
- [x] 3.3 Declare `capabilities()` with the current reference-body feed_events, action_families
      + defaults (teleport/touch off), `raw_buffer_keys=("data",)` on `frame`,
      `continuous_channels=()`, `transitional=True`.
- [x] 3.4 Assert-equal test: the adapter's descriptor equals the pre-refactor module
      constants, so drift fails CI.

## W3.5 — Stub reference adapter (`kaine/modules/mundus/adapters/stub.py`)
- [x] 3.5.1 Minimal transport-free adapter: `feed()` yields nothing (or scripted frames
      in tests), `apply_action` is a no-op that records the call, `apply_setpoints`
      accepts the five continuous channels and records them.
- [x] 3.5.2 Declare `capabilities()` with symbolic no-op families + the canonical
      continuous channels `(drive, yaw_rate, gaze_yaw, gaze_pitch, interact)`,
      `transitional=False`, empty `raw_buffer_keys`.
- [x] 3.5.3 Ships unselected and off; a core test drives it to exercise the continuous
      path (clamping, per-channel exposure, locus gate) that the reference body does not cover.

## W4 — Boot + config
- [x] 4.1 `boot.py`: read `[mundus].adapter`, construct only that adapter from its nested
      `[mundus.<adapter>]` table, inject into `Mundus`; unknown adapter → fail-closed.
- [x] 4.2 Restructure `config/kaine.toml`: `[mundus].adapter = "reference"`, move the
      reference-body keys under `[mundus.reference]`, keep `enabled = false` shipped.
- [x] 4.3 Update the config-guard test for the new shape (module still ships off).

## W5 — Regression + supersession
- [x] 5.1 Update existing Mundus tests to construct via adapter selection; confirm they
      pass unchanged otherwise (behavior preservation, `design.md` §6 acceptance).
- [x] 5.2 Add a fake in-memory adapter for core tests (no socket), exercising gating,
      locus, exposure, zero-persistence, and continuous-channel clamping.
- [x] 5.3 Annotate `reference-connector` and `paracosm-connector` as `superseded-by:
      body-agnostic-embodiment-adapters` (keep in place, not archived); re-point
      `intuitive-embodiment-control-surface`'s dependency to this change + a live adapter.
- [x] 5.4 Docs pass: update `docs/modules/mundus.md` to describe the control plane +
      adapters (present-tense, no PR refs), and the `[mundus]` config docs.
