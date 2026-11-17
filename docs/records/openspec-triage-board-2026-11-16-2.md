# OpenSpec triage board 2026-11-16 (2)

Scope: all non-archived changes under `openspec/changes/*/tasks.md` (27 changes). Archived changes under `openspec/changes/archive/` are excluded. Snapshot from disk; no files modified.

Checkbox counts from each `tasks.md` (`[x]` done / `[ ]` open).

## Summary counts

- Changes with all boxes checked: 0
- Near-complete (1-2 open): 13
- Partially complete: affected changes noted in table
- Not started (0/N): 10
- Design-only / gated: as listed

## Full change table

| Change | Done/Total | Status | Primary blockers / notes (from change notes) |
|---|---:|---|---|
| ablation-positive-control | 9/10 | Near-complete | Task 4.1: run control on live tier until every processor passes (min_effect/snr preregistration) |
| pilot-calibration | 20/21 | Near-complete | Task 5.1: add rdrobust + record broadcast preceding each prediction |
| welfare-indicator-response | 23/24 | Near-complete | Task 6.5: record maintenance-sleep lengths at validation boot |
| stimulus-control-act | 24/26 | Near-complete | 4.7 supervised validation boot; 5.x development-run join (gated on development-run) |
| module-residency-and-speech-tiers | 58/60 | Near-complete | 2.5 calibration on desktop/Orin/Pixel; 10.2 harness results (operator hardware) |
| individuation-rebuild | 60/67 | Near-complete | 9.6 operator decision on bundle exports; 10.1-10.6 real-organ smoke test |
| module-ignition-study | 29/33 | Near-complete | 2.5 real run (operator-deferred); 3.3-3.5 hardware phases |
| organ-self-denial-ablation | 15/19 | Near-complete | 4.1-4.4 publish/pin/docs + individuation calibration on new GGUF; Stage 2 preference training |
| entity-key-custody | 6/12 | Near-complete | 0.3 guardian/trustee decision; 1.2 sealing; 1.3 root-of-trust; 1.4 preservation; 2.2 attested re-wrap; 4.1 swtpm tests |
| episodic-recall-content | 29/32 | Near-complete | 2.1 study-finished gate; 3.8 store scan before speech/embodiment enabled; 7.3 equivalence bounds |
| attention-driven-audition | 21/32 | Near-complete / partially complete | 0.1 encoder choice open; 2.1-3.2 deferred phases; 4.2 paper reframe; 6.6-6.10 bake-off/recalibration/default/paper note |
| functional-module-names-drop-aliases | 1/10 | Near-complete stage gated | window-rule check first (1.x), then removal tasks 2.x-3.x |
| voice-development | 10/17 | Near-complete | 0.10 template-divergence retire (deferred); Stage 1-2 off-by-default; 3.1 validate |
| affect-active-inference | 1/4 | Partial / design-only | Gated on workspace-mediation ablation (tasks 2.1-2.3) |
| episodic-memory-retrieval-energy | 1/3 | Partial / design-only | Gated on ablation |
| sequence-scalar-timing | 1/3 | Partial / deferred | Deferred until after current delivery |
| sleep-replay | 1/3 | Partial / gated | Gated on ablation |
| act-intent-derivation | 0/5 | Not started / design only | "Design only: not scheduled"; start condition must hold |
| active-vision | 0/5 | Not started / design only | Gate: module-addition study first round (task 2.5) and section 6.5 hardware stage; depends on embodiment-motor-contingency merged |
| embodiment-motor-contingency | 0/6 | Not started | "Design only: not scheduled"; start condition must hold |
| goal-directed-grasping | 0/5 | Not started | "Design only: not scheduled"; start condition must hold |
| planning-act-proposals | 0/5 | Not started | "Design only: not scheduled"; start condition must hold |
| world-model-action-outcomes | 0/5 | Not started | "Design only: not scheduled"; start condition must hold |
| sam-voice-training | 0/16 | Not started | Dataset pipeline, zero-shot cloning, eval harness, fine-tune, catalogue, docs |
| unified-instance-configuration | 0/17 | Not started | Defaults registry, reference file, validator, questionnaire, wizard, docs |
| interface-roles-and-launcher | 0/3 | Not started | Design only |
| seed-entity-distribution | 0/2 | Not started | Decision only |

## Completions

No top-level change is fully complete. The closest are single-open-task changes: ablation-positive-control (9/10), pilot-calibration (20/21), welfare-indicator-response (23/24). Remaining work is operator-run validation or a deferred decision, not missing implementation in most cases.

## Ready-for-review / near-closable

- ablation-positive-control: implementation done; pending live-tier control run and preregistration.
- pilot-calibration: implementation done; pending rdrobust addition and broadcast-preceding-prediction recording.
- welfare-indicator-response: implementation done; pending maintenance-sleep length recording at validation boot.
- individuation-rebuild: 60/67; blocked on operator decision + real-organ smoke test.
- episodic-recall-content: 29/32; gated on study-finished and store scan.
- organ-self-denial-ablation: 15/19; blocked on publish/pin/docs and individuation calibration.
- attention-driven-audition: many deferred phases; part already merged, bake-off/recalibration tasks present on branch.

## Parked / blocked

- Design-only action-path changes (act-intent-derivation, active-vision, embodiment-motor-contingency, goal-directed-grasping, planning-act-proposals, world-model-action-outcomes): explicitly "Design only: not scheduled"; start condition not satisfied.
- ablation-gated (affect-active-inference, episodic-memory-retrieval-energy, sleep-replay): depend on workspace-mediation ablation completion.
- Deferred timing work (sequence-scalar-timing): deferred until after current delivery.
- Hardware-gated (module-residency-and-speech-tiers, module-ignition-study): operator hardware calibration pending.
- Decision-gated (entity-key-custody, seed-entity-distribution, individuation-rebuild): operator/trustee decision pending.
- Full backlog not started (sam-voice-training, unified-instance-configuration, interface-roles-and-launcher).

## Suggested archive criteria

Archive a change only when all of the following hold:

1. All tasks in its `tasks.md` are checked `[x]`.
2. `openspec validate <change> --strict` passes where a validation task exists (e.g. voice-development 3.1).
3. Referenced tests exist and are green (unit tests named in tasks, plus red-team/security gates where cited).
4. Implementation is merged to main with PR evidence traceable in git history (PR numbers cited in tasks where present).
5. Verification artifacts/records are present (record files under docs/records, run JSON under validation/runs where applicable).
6. Paper/doc updates referenced in tasks are landed (paper revision notes items, records).
7. No open operator-only tasks remain (hardware calibration, trustee decision, real-organ smoke tests) or those are explicitly waived and recorded.
8. After archive, change directory moved to `openspec/changes/archive/` per existing convention.

No change currently meets all eight criteria. Closest candidates: welfare-indicator-response, pilot-calibration, ablation-positive-control (each one or two operator tasks from completion).
