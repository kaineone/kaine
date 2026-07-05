## Context

Phase 3.1 — opening the cognition group. ONA is a mature C implementation
of NARS that has shipped a stable interactive interface for years
(read Narsese from stdin, derived statements to stdout). KAINE
integrates it as a subprocess rather than vendoring a Python NAR
implementation because the C version is the reference and the others
(pynars, narpyn's process wrapper) are thin or not maintained at the
same pace.

Constraints:
- All-local at runtime: the binary is cloned + built once at setup.
- Continuous operation: NAR runs as a long-lived subprocess; events
  feed in as Narsese, derivations come out as they're inferred.
- Portable: no system-wide ONA install. The binary lives inside the
  repo's `external/` directory so the same checkout reproduces the
  same environment on a different host.
- Testable without the binary: subprocess management is replaceable so
  CI / fresh-clone tests pass without first running the build script.

Stakeholders: Mnemos (Phase 3.2) consolidates Nous's beliefs.
Syneidesis can use Nous's derivations as future salience inputs.
Eidolon observes the workspace shaped by Nous-derived content.

## Goals / Non-Goals

**Goals:**
- A `Nous(BaseModule)` that spins up NAR on initialize, translates each
  workspace broadcast's selected events into Narsese statements, feeds
  them to NAR, polls for derivations, and publishes new beliefs as
  `nous.belief` events.
- `(frequency, confidence)` truth-value pairs in every published
  belief, exactly as ONA reports them — KAINE does not invent
  truth-values.
- Subprocess lifecycle: clean startup, graceful shutdown on module
  shutdown, automatic restart on unexpected NAR exit (with a backoff
  cap, surfaced as a Soma alert via salience).
- A setup script (`scripts/build-ona.sh`) that produces the binary on
  a fresh clone in one command.
- Tests run without the ONA binary; one opt-in test exercises the real
  binary.

**Non-Goals:**
- Rich Narsese translation. v1 emits a simple inheritance template per
  event; future changes can add temporal, copula, and compound terms.
- Goal-directed inference (NAL-8). Nous v1 publishes derivations only;
  Praxis-driven goal injection lands in a later change.
- Multiple NAR processes. One subprocess per Nous instance.
- Persisting NAR state across restarts. Phase 6 Hypnos handles
  consolidation; Phase 3.1 starts with a fresh memory.

## Decisions

**ONA upstream lives in `external/OpenNARS-for-Applications/`.** The
build script clones-or-fetches into that path. `external/` is gitignored
because (a) upstream sources should not appear in KAINE's history as
unrelated commits, and (b) build artifacts are large and per-host.

**Setup script is idempotent.** `scripts/build-ona.sh` checks for an
existing clone (pulls latest), checks for the existing binary
(skips rebuild if newer than source), and runs `./build.sh` from
upstream only when needed. The script exits non-zero if the binary
fails to launch (smoke test reads version line).

**Subprocess: `asyncio.create_subprocess_exec` with line-buffered
stdin/stdout.** NAR's interactive mode reads Narsese line-by-line.
The wrapper writes lines and reads lines back, parsing the output for
`Derived:`, `Revised:`, `Answer:` lines. `stderr` is captured and
logged.

**`NARProcessProtocol` defines the abstraction.** Real `NARProcess`
implements it; `FakeNARProcess` for tests returns canned derivation
streams. The protocol exposes `start`, `stop`, `send`, `read_pending`,
`step(n)`. This keeps the module testable without the binary.

**Narsese statement template, v1:**
- Events with `causal_parent=None`:
  `<{source} --> [{type}]>. :|: %{salience};0.9%`
- Events with a known causal parent:
  Two statements — the parent's term, then
  `<{parent_term} =/> {child_term}>. :|: %0.9;0.7%` (temporal
  implication). The temporal copula `=/>` captures "leads to."
- `source` and `type` are slugified into Narsese atoms
  (letters/digits/underscore; non-ASCII collapsed; reserved chars
  escaped).

**Truth-value carries through unchanged.** ONA emits `%f;c%` for every
statement; the parser extracts those floats and publishes them as
`{"frequency": float, "confidence": float}` in the event payload.
KAINE does not normalize, clamp, or re-interpret.

**Step-driven inference rather than free-running.** After feeding new
events each tick, the module sends `inference_steps_per_tick` as a
control input (`<N>` followed by newline asks NAR to run N steps).
Default 10 — enough to derive a few beliefs per tick without blocking
the event loop.

**Restart with exponential backoff.** If NAR exits unexpectedly, the
module restarts it. Backoff starts at 0.5 s, doubles to a 30 s cap,
resets after 5 minutes of stable operation. Each restart publishes a
high-salience `nous.restart` event so Syneidesis surfaces it.

**Published events use type `nous.belief` for derivations and
`nous.restart` for lifecycle.** Salience is the belief's confidence by
default — high-confidence derivations are salient. Operators can
override the salience mapper via config.

## Risks / Trade-offs

- **ONA upstream build may break on this host.** → Build script
  surfaces the failure with the upstream's log output; documented as
  an operator action.
- **NAR's output format is line-based but tokens vary across
  versions.** → Parser is permissive (skip unknown lines, warn on
  unexpected ones).
- **A flood of events overwhelms NAR.** → Per-tick inference budget
  caps the per-tick work. The bus's MAXLEN trim caps the input rate.
- **Naïve translation collapses distinct events into the same
  Narsese atom.** → v1 cost; future translator versions can mix in
  payload features.

## Migration Plan

First implementation. Nous is registered in code paths but not
auto-added to the registry; the first-boot script wires it up when
the operator opts in.

## Open Questions

- Whether to derive truth-values from Soma's wellness when translating
  hardware events (e.g. high temp → lower confidence). Deferring;
  build prompt §3.1 is explicit that beliefs carry truth-values
  *from ONA*, not from KAINE assignment.
- Whether to plumb Narsese-formatted goals from Thymos (Phase 4) into
  NAR via NAL-8 `!` operator. Deferring to Phase 4.
