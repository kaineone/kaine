# Proposal completion pulse — 2026-11-16

Scope: all 27 non-archived changes under `openspec/changes/` (archived changes excluded).
Task counts from each `tasks.md` (`[x]` done / total checkbox). No specs or source files were modified.

Snapshot totals: **309/445 tasks (69.4%)** across the 27 active changes.

## Classification key

- **ready** — code complete; only one operator/validation task remains before the change is closable (no unimplemented sections).
- **near-candidate** — substantially complete (>=85%), but more than one unchecked task remains; closable after listed validation/gating tasks.
- **blocked** — partial implementation with active gating dependencies (ablation studies, hardware, decisions, validation, release window).
- **parked** — design-only, not scheduled, operator-deferred backlog, or explicitly parked; no implementation started (or none scheduled).

## Ready (3)

| Change | Done/Total | Remaining |
|---|---:|---|
| ablation-positive-control | 9/10 | live-tier control run until every processor passes (min_effect/snr preregistration) |
| pilot-calibration | 20/21 | add rdrobust + record broadcast preceding each prediction |
| welfare-indicator-response | 23/24 | record maintenance-sleep lengths at validation boot |

## Near-candidate (5)

| Change | Done/Total | Remaining gate |
|---|---:|---|
| module-residency-and-speech-tiers | 58/60 | 2.5 calibration on desktop/Orin/Pixel; 10.2 harness results (operator hardware) |
| stimulus-control-act | 24/26 | 4.7 supervised validation boot; 5.x development-run join (gated on development run) |
| episodic-recall-content | 29/32 | 2.1 study-finished gate; 3.8 store scan before speech/embodiment enabled; 7.3 equivalence bounds |
| individuation-rebuild | 60/67 | 9.6 operator decision on bundle exports; 10.1-10.6 real-organ smoke test |
| module-ignition-study | 29/33 | 2.5 real run (operator-deferred); 3.3-3.5 hardware phases |

## Blocked (9)

| Change | Done/Total | Gate / blockers |
|---|---:|---|
| attention-driven-audition | 21/32 | 0.1 encoder choice open; 2.1-3.2 deferred phases; 4.2 paper reframe; 6.6-6.10 bake-off/recalibration/default/paper note |
| organ-self-denial-ablation | 15/19 | 4.1-4.4 publish/pin/docs + individuation calibration on new GGUF; Stage 2 preference training |
| entity-key-custody | 6/12 | 0.3 guardian/trustee decision; 1.2 sealing; 1.3 root-of-trust; 1.4 preservation; 2.2 attested re-wrap; 4.1 swtpm tests |
| functional-module-names-drop-aliases | 1/10 | blocked until first release cut and 90-day window (ALIAS_LAST_RELEASE stays 27.02) |
| voice-development | 10/17 | 0.10 template-divergence retire (deferred); Stage 1-2 off-by-default; 3.1 validate |
| affect-active-inference | 1/4 | gated on workspace-mediation ablation (tasks 2.1-2.3) |
| episodic-memory-retrieval-energy | 1/3 | gated on ablation |
| sequence-scalar-timing | 1/3 | deferred until after current delivery |
| sleep-replay | 1/3 | gated on ablation |

## Parked (10)

| Change | Done/Total | Status |
|---|---:|---|
| act-intent-derivation | 0/5 | design only: not scheduled |
| active-vision | 0/5 | design only; depends on embodiment-motor-contingency merged and module-addition study |
| embodiment-motor-contingency | 0/6 | design only: not scheduled |
| goal-directed-grasping | 0/5 | design only: not scheduled |
| planning-act-proposals | 0/5 | design only: not scheduled |
| world-model-action-outcomes | 0/5 | design only: not scheduled |
| interface-roles-and-launcher | 0/3 | design only |
| seed-entity-distribution | 0/2 | decision only / under consideration |
| unified-instance-configuration | 0/17 | PARKED (roadmap item, not active work) |
| sam-voice-training | 0/16 | non-priority roadmap item; does not block entity or development run |

## Aggregate by class

| Class | Changes | Done/Total | % |
|---|---:|---:|---:|
| ready | 3 | 52/55 | 94.5% |
| near-candidate | 5 | 200/218 | 91.7% |
| blocked | 9 | 56/103 | 54.4% |
| parked | 10 | 0/61 | 0.0% |
| **all active** | **27** | **309/445** | **69.4%** |

## Notes

- No change currently has all task boxes checked; none is an immediate archive candidate under the all-boxes-checked rule (see `docs/records/openspec-archive-candidate-2026-11-16.md`).
- Classification reflects on-disk task state only; runtime/verification evidence and merges were not re-audited here.
