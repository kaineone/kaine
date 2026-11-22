# Review: module-core

## Lead review (2026-11-22)

I checked the design against the code on `main` at `eac350195`. Findings R1 to R5 were found in the first draft and are fixed in the current design. R6 to R8 are open points carried into the tasks.

**R1, fixed (D5): the default context would have invented a clock.** The first draft let `BaseModule` build a default `ModuleContext` from "the process services". Modules may not import the cycle, which owns the entity clock, and today boot passes the clock only to the eight factories in `_CLOCKED_FACTORIES` (`kaine/boot/registry.py:80`). A default would have had to be a wall-speed clock, which ignores `time_scale`: exactly the dilation bug this change removes, now hidden behind a shared service. Fix: the registry attaches a context to every module before `initialize()` (`attach_context`, mirroring `attach_oscillator`), and reading an unattached context raises.

**R2, fixed (D7): golden digests would have depended on the machine.** `kaine/modules/audition/forward.py:89` uses torch, and the stimulus-off golden already fails on the local CUDA build while passing on CI's CPU build. A checked-in digest alone would either fail locally or, if the factory skipped it, go unchecked during the migration. Fix: CI checks the digests recorded on its CPU environment, and each migration's review also runs a same-machine trace comparison of `main` against the branch.

**R3, fixed (D7): a registry filled at import would change the processor roster.** `kaine/workspace/feedback.py:47` lists all three processors whether or not each is enabled. A registry filled by module import side effects would drop a processor that is not imported, which changes the feedback controller's gains and the content level's sources. Fix: the registry is declared data, and a test checks each entry against its module.

**R4, fixed (D6): periodic work needs a choice of clock.** Health pollers, client reconnects and the heartbeat must run on real time, while cognitive timers run on entity time. `spawn(..., every_s=...)` takes `clock="entity"` (the default) or `clock="wall"`.

**R5, fixed (D10): the state envelope and the latent strip touch the same paths.** `latent-content-privacy` task 2.3 strips latents from module state at fork snapshot, preservation and resume checkpoint, which are the same three call sites group 7 changes. Group 7 now lands after it, and wraps state after the strip.

**R6, open: dev-mode raising in `publish` needs a list of what is registered at first.** If `KAINE_DEV_VALIDATE=1` is set in the test suite before every producer has a contract test, unrelated tests fail on payloads nobody has modelled yet. Task 4.1 registers types only together with their producer contract test, and the suite sets the variable only for registered types.

**R7, open: the payload models must be built from the producers' code.** A model written from reading consumers would encode what consumers guess, not what producers send. Tasks 4.2 and 4.3 require each contract test to build its payload by calling the producer's own report-building function.

**R8, open: the contract page has to stay honest as groups land.** The page marks each item in force or adopting. Task 8.1 updates the marks with each group, and the conventions test makes most "adopting" items checkable, so a mark can be confirmed against a baseline of zero.

Verdict: accept for implementation in the task order given. Groups 5 and 7 each need a second review per PR. The two open questions in the design go to the operator; neither blocks groups 1 to 4.

## Independent gap analysis (kimi-k3, 2026-11-22)

kimi-k3 read the proposal, the design, the tasks and the contract page as they stood after R1 to R5, and returned 26 findings with the verdict "accept with changes". Each finding and the response:

| # | Finding (short) | Response |
|---|---|---|
| 1 | Consumers of registered types never scheduled to migrate | Accepted: task 4.3a, one PR per type; the literal ratchet now covers module code too (1.3) |
| 2 | No rule for payload key names (`ts`/`timestamp`) | Accepted: task 4.3b; the contract page says timestamps come from the envelope |
| 3 | D2 and Risks disagreed on where contract-test payloads come from | Accepted: both now say the producer's own code (D2) |
| 4 | No task makes modules declare their dependencies | Accepted: task 3.4a names the six modules |
| 5 | Production enforcement deferred with no exit | Accepted: production enforcement is out of scope by decision (D2) |
| 6 | Moving clock calls to entity time changes behaviour under freeze | Accepted: per-site classification, default to `wall()`, freeze and dilation tests (D11) |
| 7 | The language publish fix's oscillator behaviour unspecified | Already handled: the Fabro plan passes `drive_oscillator=False`, keeping today's behaviour |
| 8 | `subscribe` changes restart behaviour; key collision | Accepted: per-consumer statement, reserved `_cursors` key (D11) |
| 9 | `spawn` log-and-continue hides failures | Accepted: failures count in `health()`; log-only is opt-in (D11) |
| 10 | Dataclass bounds would refuse working operator files | Accepted: warn for one release (D11) |
| 11 | Import-time registry gives a partial roster; blend not digested | Roster: already fixed (R3). Blend digest: accepted (task 5.1) |
| 12 | Validation on the production hot path | Accepted: production `publish` does no validation (D2) |
| 13 | Goldens recorded after other groups may have changed the processors | Accepted: 5.1 runs first; the processors are excluded from the context batches (D11) |
| 14 | The page teaches mechanisms that do not exist yet | Accepted: third mark, "specified" (D11), applied on the page |
| 15 | Unstated group order; 7.2 before its round-trip gate; Q1 without a task | Accepted: order stated; round-trip test is now 7.2, before the call sites (7.3); Q1 is a separate change either way |
| 16 | Bit-identical migration cements the unsafe `getattr(..., True)` default | Accepted in part: the default never applies today (all three set the flag), and `PredictionResult` removes it with no output change; the harness covers skipped, NaN and first-reading steps (D11) |
| 17 | Validation errors could log content or latent values | Accepted: messages name the type and field paths only (D2) |
| 18 | A refused module restore has no policy | Accepted: pre-flight over the whole bundle; the restore is refused as a whole and reported (D11, task 7.3) |
| 19 | The real bundle is never tested | Accepted: task 7.4, read-only and supervised |
| 20 | The latent opt-out can spread | Accepted: ratchet kind (task 1.4) |
| 21 | The state format change is one-way | Accepted: backup before the release, noted as one-way (task 7.4) |
| 22 | "In force" time rule is false on `main` | Accepted: now marked adopting, with the ratchet as its guard |
| 23 | Salience mapping marked in force covers processors that differ | Accepted: in-force claim limited to non-processor modules |
| 24 | Reference-config generator not on `main` | Rejected: `scripts/generate_reference_config.py` and `tests/test_config_reference_drift.py` are on `main` |
| 25 | Declared consumers list would rot | Accepted: dropped from `EventSpec` |
| 26 | N-source blending is premature | Accepted: kept at three sources; registry only (D11) |

Verdict after the revisions: accept. The design, tasks and page were revised as above and the change validates under `openspec validate --strict`.
