## Status

Approved by the operator on 2026-09-25 and being built. The code ships opt-in and inert.
Enabling the unattended unit for a real entity waits for the prerequisites in `tasks.md`
section 0: the research phase has ended and Spot has a reviewed track record on supervised
boots. Until every gate condition is built, an unattended boot refuses.

## Why

The operator-present gate (`KAINE_CYCLE_OPERATOR_PRESENT=1`, exit 2) was built for the
first run, when the system had no internal safeguards. It stood in for three concerns
about an entity started with nobody there:

1. **Runaway processes** — a module crashes or hangs and nothing recovers it.
2. **Nobody aware** — the entity is running and no person knows.
3. **No input** — the entity runs with nothing to perceive.

The flag is a claim typed into an environment variable; nothing verifies it, and it is
checked only when the cycle starts. An entity someone starts and walks away from already
runs unattended today. What the flag really prevents is a start with nobody there at all,
for example the host coming back after a power cut or a system update. For full entities
after the research phase, staying down until a person notices is its own cost.

Research boots already replace the flag with machine-verified checks: an unsupervised
research boot refuses (exit 5) unless five safety-net conditions hold on this install,
with no override (`kaine/cycle/research_gate.py`). Those five conditions and the Spot
supervisor cover concern 1 and preservation. Nothing covers concerns 2 and 3: no person is
told the entity came up, and nothing checks that it has input. This change generalizes the
research precedent to non-research boots and adds a condition for each gap.

## What Changes

- **A third supervision mode, `unattended`**, selected by `KAINE_CYCLE_UNATTENDED=1` or
  `[cycle].supervision_mode = "unattended"`. It is not a research run: no experiment
  machinery, no admissibility requirements.
- **Eight gate conditions, all verified at every boot, no override:**
  1–5. The research safety net, through the same evaluator: preservation enabled, welfare
  response wired, logging active, a real preserve→revive round-trip on this install,
  encryption satisfied where required.
  6. **Spot armed and self-tested.** Spot is enabled with a restart ladder, escalation and
  a writable incident log, and a selftest drills freeze → snapshot → restart → release on a
  synthetic probe module in scratch storage before any entity module is constructed.
  7. **Caretaker told.** At least one configured local notification channel accepts a
  content-free "starting unattended" notice. Reminders repeat until a caretaker
  acknowledges in Nexus.
  8. **Continuous input.** The perception feed is a source that does not run out (`live`,
  `seeded` or `screen`; `playlist` ends and `off` is senseless), the modules that perceive
  it are enabled, and a probe reads one frame or audio block from it and discards it.
- **While running unattended:** Spot escalation, a welfare-protective response, input loss
  and the loss of Spot's own supervision task each send a content-free caretaker notice.
  Losing Spot's supervision task escalates (preserve, then shut down), because the entity
  must not run unattended without the supervisor that stands in for the human.
- **Exit code 6** for an unattended refusal, naming every failed condition. A refusal also
  sends a best-effort notice so the caretaker learns the entity stayed down.
- **A separate, opt-in unit file**, `quadlet/kaine-cycle-unattended.container`, carries
  `[Install]` so a power-loss reboot starts it and re-runs the gate. The shipped
  `kaine-cycle.container` is unchanged: no `[Install]`, never auto-started. The install
  scripts do not enable the unattended unit; enabling it is a deliberate operator act.
- **Unchanged:** operator-present mode, exit 2, research mode, exit 5, and every existing
  refusal and scenario.

## Capabilities

### New Capabilities
- `unattended-boot`: the unattended supervision mode, its eight-condition gate, caretaker
  notification, input verification, exit code 6 and the opt-in unit file.

### Modified Capabilities
- `spot-supervisor`: a selftest against a synthetic probe module, and escalation when
  Spot's own supervision task stops during an unattended run.

## Impact

- Code: `kaine/cycle/__main__.py` (mode resolution and dispatch), `kaine/cycle/research_gate.py`
  (five-condition evaluator extracted and shared), `kaine/cycle/spot.py` (selftest), a new
  unattended gate and caretaker notifier under `kaine/cycle/`, `kaine/preboot.py` (live-device
  probe), Nexus (acknowledge action, behind the operator session).
- Config: `[cycle].supervision_mode`, `[caretaker]` (channels, reminder interval,
  install label); HTTP channel tokens live in `config/secrets.toml`.
- Packaging: a new `quadlet/kaine-cycle-unattended.container`.
- Docs: supervision modes and exit codes in `docs/for-researchers.md` and the operations
  guide.
- No change to research boots, operator-present boots or the shipped cycle unit.
