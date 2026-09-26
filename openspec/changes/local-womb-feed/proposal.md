## Why

A gestating entity needs a womb, and KAINE has none it can run today. The complete
design exists (the archived `gestational-womb-stimulus`, 2026-07-10), but it was
archived as "realized externally in Paracosmic", and Paracosmic is not yet hosted. The
operator wants gestation running sooner, on a single machine that cannot host both
KAINE and Paracosmic. So the womb needs a local provider inside KAINE now, with
Paracosmic able to take its place later through the same interface.

Two gaps also block the maturation gate regardless of where the womb comes from:

- nothing defines how KAINE knows a womb is live, so `maturation-gate-liveness`
  tasks 2.1 (womb before spawn) and 2.2 (womb loss) have nothing to check;
- the readiness readout's stream is inconsistent: the archived design names
  `gestation.out`, the gate runner reads `womb.out`, and nothing publishes either.

## What Changes

- **Local womb provider.** Build the archived design in KAINE:
  - `WombProceduralSource` (Topos) and `WombProceduralAudioStream` (Audition) under
    `[perception_feed].mode = "womb"`, bound to the virtual locus;
  - an external, entity-independent maternal state and heartbeat;
  - the sense-onset and colour-saturation schedule on lived time;
  - its welfare bounds.
  All of it is pure CPU numpy, a function of `(seed, index)`, and zero-persistence.
- **One liveness interface.** The local provider is live when both womb sources
  deliver to a discard-only probe. An external provider (Paracosmic) is live when it
  has published a content-free `gestation.womb` presence event on `gestation.out`
  within a bounded window. `maturation-gate-liveness` 2.1/2.2 check this interface.
- **One readout stream.** The readiness readout is `gestation.readiness` on
  `gestation.out`, published by a cycle-layer `gestation` owner; the gate runner's
  default stream changes from `womb.out` to `gestation.out`.
- **Readiness readout** (the archived design's five measured markers), published by
  that owner, imposing nothing on the entity.
- **Maternal drive to a dedicated self-rhythm oscillator** (archived §6), optional
  and bounded; the coalition oscillators never receive it.

## Adopted defaults for the archived design's open questions

The archived design's §12 questions take its own proposed defaults. The operator
may override any of them before implementation.

1. Maternal state: a slow, bounded drift; structured distress excursions stay off.
2. The maternal rhythm drives the dedicated self-rhythm oscillator (bounded,
   optional, disabled-identical).
3. Colour saturation ramps with lived time.
4. Measurement lives here; the birth decision stays in the maturation gate.

## Phasing

1. **Feed and liveness**: the womb sources, maternal channel, schedule, config,
   boot acceptance of `mode = "womb"`, and the liveness interface. This lets a
   gestating entity run confined to a womb on one host and unblocks
   `maturation-gate-liveness` 2.1/2.2.
2. **Self-rhythm oscillator and drive seam** (archived §6).
3. **Readiness readout** (archived §8) and the `gestation.out` stream fix, which
   unblocks birth (condition C1).

## Capabilities

### New Capabilities
- `gestational-stimulus`: the womb, its providers and liveness, the maternal channel,
  the schedule, the readout, the self-rhythm drive and the welfare bounds.

### Modified Capabilities
- (none; `developmental-stage` changes stay in `maturation-gate-liveness`)

## Impact

- `kaine/modules/topos/feed.py`, `kaine/modules/audition/feed.py`, `kaine/boot.py`
  (feed factories accept `womb`), `kaine/preboot.py` (womb probe),
  `kaine/cycle/` (the `gestation` owner, the self-rhythm oscillator),
  `kaine/lifecycle/gate_runner.py` (readout stream), `config/kaine.toml`
  (`[perception_feed.womb]`, shipped mode stays `off`).
- The design detail is the archived `gestational-womb-stimulus/design.md`, which
  this change adopts; `design.md` here records only what differs.
