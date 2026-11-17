# OpenSpec dry-run preparedness (2026-11-16)

Task-doc only. Snapshot of non-archived OpenSpec changes and runnable smoke ingests. No files modified by this record.

## Changes that remain open

No non-archived change has all tasks checked. All 27 listed in `docs/records/openspec-triage-board-2026-11-16-2.md` remain open; source-of-truth counts are on disk in each `openspec/changes/<change>/tasks.md`.

Summary from that board:

| Change | Done/Total | Status |
|---|---:|---|
| ablation-positive-control | 9/10 | Near-complete |
| pilot-calibration | 20/21 | Near-complete |
| welfare-indicator-response | 23/24 | Near-complete |
| stimulus-control-act | 24/26 | Near-complete |
| module-residency-and-speech-tiers | 58/60 | Near-complete |
| individuation-rebuild | 60/67 | Near-complete |
| module-ignition-study | 29/33 | Near-complete |
| organ-self-denial-ablation | 15/19 | Near-complete |
| entity-key-custody | 6/12 | Near-complete |
| episodic-recall-content | 29/32 | Near-complete |
| attention-driven-audition | 21/32 | Near-complete / partially complete |
| functional-module-names-drop-aliases | 1/10 | Gated (window rule first) |
| voice-development | 10/17 | Near-complete |
| affect-active-inference | 1/4 | Partial / design-only |
| episodic-memory-retrieval-energy | 1/3 | Partial / design-only |
| sequence-scalar-timing | 1/3 | Partial / deferred |
| sleep-replay | 1/3 | Partial / gated |
| act-intent-derivation | 0/5 | Not started / design only |
| active-vision | 0/5 | Not started / design only |
| embodiment-motor-contingency | 0/6 | Not started |
| goal-directed-grasping | 0/5 | Not started |
| planning-act-proposals | 0/5 | Not started |
| world-model-action-outcomes | 0/5 | Not started |
| sam-voice-training | 0/16 | Not started |
| unified-instance-configuration | 0/17 | Not started |
| interface-roles-and-launcher | 0/3 | Not started |
| seed-entity-distribution | 0/2 | Not started |

## Nearest completable tasks

Changes with 1-2 open tasks; remaining checkboxes quoted from disk:

- ablation-positive-control: `4.1 Fix min_effect and snr with the preregistration and run the control on the live tier until every processor passes`
- pilot-calibration: `5.1 Add rdrobust and record which broadcast preceded each prediction, for theta_band, b_band and the age bins`
- welfare-indicator-response: `6.5 At the validation boot, record the length of every maintenance sleep, to check the matured completion bound against them.`
- stimulus-control-act: `4.7 One supervised validation boot on a branch before the join.`; `6.1 After act-intent-derivation, drive-reduction-learning and learned-action-selection: the act bar replaces the drive-led trigger and learned advantages choose the action. Tests: tests/test_stimulus_stage_l.py.`
- module-residency-and-speech-tiers: `2.5 Operator step: run calibration on this desktop, the Orin Nano Super and the Pixel 6a, and commit the results under docs/benchmarks/.`; `10.2 Operator step: run the harness on the Orin Nano Super, the Pixel 6a and this desktop; commit results under docs/benchmarks/.`
- episodic-memory-retrieval-energy: `2.1` deferred separation check; `2.2` deferred config gate.
- sequence-scalar-timing: `2.1` deferred peak-interval test; `2.2` deferred SBF/Laplace mechanism.
- sleep-replay: `2.1` deferred interference benchmark; `2.2` deferred replay_consolidate protocol.
- seed-entity-distribution: `1.1` decision on distributing a matured seed entity; `1.2` bundle/key/licence design if yes.

## Smoke test ingestion commands

```bash
.venv/bin/python scripts/tier1_smoke.py
.venv/bin/python -m kaine.preboot
.venv/bin/python openspec/changes/individuation-rebuild/validation/smoke.py \
  --config config/kaine.toml \
  --operator-config config/kaine.operator.toml \
  --samples 40 --splits 1000 --controls 200 --seed 1234 \
  --out openspec/changes/individuation-rebuild/validation/runs
```

## Verification

```bash
python3 - <<'PY'
import glob,json,os
p=max(glob.glob("openspec/changes/individuation-rebuild/validation/runs/smoke-*.json"), key=os.path.getmtime)
d=json.load(open(p))
print(p)
print("acceptance:", d.get("acceptance"))
PY

grep -R '"passed": true' openspec/changes/individuation-rebuild/validation/runs/*.json | tail -n 5

openspec validate individuation-rebuild --strict

.venv/bin/python -m pytest -q \
  tests/test_preboot_smoke.py \
  tests/test_individuation_smoke_harness.py \
  tests/test_individuation_simulate_smoke.py
```

Rules for closing a change: all tasks checked, strict OpenSpec validation green where applicable, referenced tests present and green, implementation merged with traceable PR evidence, verification artifacts present, docs/paper updates landed, no unwaved operator-only tasks, then move the change under `openspec/changes/archive/`.
