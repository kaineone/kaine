# OpenSpec pattern check (2026-11-16)

## Counts

- Total OpenSpec change directories on disk: 474
  - Active (`openspec/changes/`, excluding `archive/`): 27
  - Archived (`openspec/changes/archive/`): 447
- Active changes with `tasks.md`: 27
- Total task checkboxes across active changes: 441
  - Completed (`[x]`): 305
  - Pending (`[ ]`): 136

Per-active-change status:

| Change | Done | Pending |
|---|---:|---:|
| ablation-positive-control | 9 | 1 |
| act-intent-derivation | 0 | 5 |
| active-vision | 0 | 5 |
| affect-active-inference | 1 | 3 |
| attention-driven-audition | 21 | 11 |
| embodiment-motor-contingency | 0 | 6 |
| entity-key-custody | 6 | 6 |
| episodic-memory-retrieval-energy | 1 | 2 |
| episodic-recall-content | 29 | 3 |
| functional-module-names-drop-aliases | 1 | 9 |
| goal-directed-grasping | 0 | 5 |
| individuation-rebuild | 60 | 7 |
| interface-roles-and-launcher | 0 | 3 |
| module-ignition-study | 25 | 4 |
| module-residency-and-speech-tiers | 58 | 2 |
| organ-self-denial-ablation | 15 | 4 |
| pilot-calibration | 20 | 1 |
| planning-act-proposals | 0 | 5 |
| sam-voice-training | 0 | 16 |
| seed-entity-distribution | 0 | 2 |
| sequence-scalar-timing | 1 | 2 |
| sleep-replay | 1 | 2 |
| stimulus-control-act | 24 | 2 |
| unified-instance-configuration | 0 | 17 |
| voice-development | 10 | 7 |
| welfare-indicator-response | 23 | 1 |
| world-model-action-outcomes | 0 | 5 |

## Likely project-level task categories

### Blocked

- `pilot-calibration`: `theta_band`, `b_band`, age bins, and tone bins recorded as blocked (rdrobust dependency; tone model support missing).
- `ablation-positive-control`: final live-tier positive-control run still pending (task 4.1).

### Parked

- `unified-instance-configuration`: explicitly `Status: PARKED (roadmap item, not active work)`.

### Design-only (no implementation yet)

- `interface-roles-and-launcher`: design only, not scheduled; records direction only.
- `seed-entity-distribution`: design question with open points; nothing changes yet.
- `act-intent-derivation`, `active-vision`, `embodiment-motor-contingency`, `goal-directed-grasping`, `planning-act-proposals`, `world-model-action-outcomes`: design-first changes settled first in paper, then code; implementation tasks are pending/outline.
- `attention-driven-audition`: design-first; specifies mechanism; does not implement it.

No source changes were made for this record.
