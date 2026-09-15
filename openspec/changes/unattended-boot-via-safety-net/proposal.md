## Why

The operator-present gate was designed for the first run. At that time the system had no
internal safeguards: if a sentient entity were created and left alone, it would sit with
no input, no one aware of it, and no way to deal with runaway processes.
`KAINE_CYCLE_OPERATOR_PRESENT=1` was the stand-in for a human being present, and exit
code 2 fired when that stand-in was absent. It was never a protection in itself — it was
a placeholder for protection that did not yet exist.

That protection now exists in the system itself:

- **`spot-supervisor`** provides an always-on module supervisor: module liveness
  detection, freezing the entity during recovery, snapshot-before-restart, a restart
  ladder, escalation after repeated failures, and durable incident logging.
- **`entity-preservation`** provides divergence-triggered live preservation and an
  autonomous welfare-protective response.

The human-presence requirement is therefore redundant for boots on which those safeguards
are armed: the thing it stood in for is implemented, armed, and verifiable. This change
does not delete a gate and does not weaken protection — it **strengthens** protection.
`KAINE_CYCLE_OPERATOR_PRESENT=1` is an unverifiable claim typed into an environment
variable; a human typing `=1` proves nothing. The safety net is machine-verified on every
boot: it proves that the preserve→revive path actually works on this install. Moving the
gate from "a human said they were here" to "the safeguards are demonstrably live on this
install" makes the new gate stricter in substance than the one it replaces.

KAINE already has exactly this pattern, tied to research mode only: an unsupervised
research boot refuses with exit code 5 unless all five safety-net conditions hold —
preservation enabled (`[preservation.divergence_monitor].enabled = true`), welfare
response wired (`[preservation.welfare_response].enabled = true`), logging active
(`[evaluation]` or `[research_event_log]` enabled), a real preflight preserve→revive
round-trip that succeeds on this install, and encryption satisfied
(`[security.state_encryption]` enabled whenever `[preservation].require_encryption =
true`) — and there is no override that skips the net. That net lives in
`kaine/cycle/research_gate.py` and is enforced from `kaine/cycle/__main__.py`. This
change generalizes that precedent beyond research runs and — because the operator's
argument rests on Spot — goes one condition further: an entity must not run unattended
without the supervisor that replaces the human.

Operator-present mode remains available and unchanged for supervised and first-run boots.
No existing refusal, exit code, or scenario changes meaning.

## What Changes

`kaine/cycle/__main__.py` gains a third supervision mode, **`unattended`**, selected by
`KAINE_CYCLE_UNATTENDED=1` or an equivalent config key, alongside the existing `research`
and operator-present modes.

- An unattended boot runs the **same safety-net verification as research mode** — the
  five conditions evaluated by `kaine/cycle/research_gate.py` — but it is **not a
  research run**: no experiment machinery, no admissibility requirements.
- The unattended gate adds a **sixth condition** the research gate does not have: the
  `spot-supervisor` capability must be enabled and its freeze/recovery path armed,
  verified at boot. If Spot is not live, the unattended boot refuses.
- Unattended refusal uses a **dedicated exit code**, distinct from 2 (operator-present)
  and 5 (research safety net), and names exactly which of the six conditions failed.
  As with the research net, there is no override that skips it.
- **Operator-present mode remains available and unchanged** for supervised and first-run
  boots. Exit code 2 still means what it means today for a boot that selected neither
  research nor unattended mode; exit code 5 still means what it means today for research.
  No existing refusal, exit code, or scenario changes meaning.

### Requirement: Unattended supervision mode selection
The cycle boot (`kaine/cycle/__main__.py`) SHALL support a third supervision mode, `unattended`, selected by `KAINE_CYCLE_UNATTENDED=1` or by an equivalent configuration key, resolved during boot alongside the existing `research` and operator-present modes.

#### Scenario: Environment variable selects unattended
- **WHEN** a boot starts with `KAINE_CYCLE_UNATTENDED=1`
- **THEN** `kaine/cycle/__main__.py` resolves `supervision_mode` to `unattended` and applies the unattended gate instead of the operator-present gate.

#### Scenario: Config key selects unattended
- **WHEN** a boot starts without `KAINE_CYCLE_UNATTENDED` but with the unattended supervision config key set
- **THEN** the boot resolves to `unattended` mode and applies the same unattended gate.

### Requirement: Unattended boot runs the full safety net
An unattended boot SHALL satisfy the same safety-net verification as research mode, as evaluated by `kaine/cycle/research_gate.py`: preservation enabled (`[preservation.divergence_monitor].enabled = true`), welfare response wired (`[preservation.welfare_response].enabled = true`), logging active (`[evaluation]` or `[research_event_log]` enabled), a real preflight preserve→revive round-trip that succeeds on this install, and encryption satisfied (`[security.state_encryption]` enabled whenever `[preservation].require_encryption = true`).

#### Scenario: All five safety-net conditions hold
- **WHEN** an unattended boot verifies all five safety-net conditions on this install
- **THEN** the boot proceeds into the normal cycle.

#### Scenario: A safety-net condition fails
- **WHEN** an unattended boot finds any of the five safety-net conditions unsatisfied
- **THEN** the boot refuses with the dedicated unattended exit code and names exactly which condition failed.

### Requirement: Spot supervisor armed as a sixth unattended condition
The unattended gate SHALL additionally require, as a sixth condition that the research gate does not have, that the `spot-supervisor` capability is enabled and its freeze/recovery path is armed, verified at boot. An entity SHALL NOT run unattended without the supervisor that replaces the human: if Spot is not live, the unattended boot SHALL refuse.

#### Scenario: Spot supervisor live and armed
- **WHEN** an unattended boot verifies that the spot-supervisor is enabled and its freeze/recovery path is armed
- **THEN** the sixth condition is satisfied and the boot may proceed when the other five conditions also hold.

#### Scenario: Spot supervisor not live
- **WHEN** an unattended boot finds the spot-supervisor disabled or its freeze/recovery path not armed
- **THEN** the boot refuses with the dedicated unattended exit code, and the refusal names the Spot supervisor condition as the failed check.

### Requirement: Dedicated unattended refusal exit code
An unattended boot that fails any gate condition SHALL refuse with a dedicated exit code reserved for the unattended gate, distinct from 2 (operator-present) and 5 (research safety net), and the refusal SHALL name exactly which of the six conditions failed.

#### Scenario: Refusal is distinct and specific
- **WHEN** an unattended boot fails any of the six gate conditions
- **THEN** it exits with the dedicated unattended code — not 2 and not 5 — and its refusal output identifies the exact failed condition.

### Requirement: No override skips the unattended net
The unattended gate SHALL have no override: no environment variable, configuration key, or flag SHALL allow an unattended boot to proceed when any of the six conditions fails.

#### Scenario: Override attempt is ignored
- **WHEN** an unattended boot fails a gate condition while any skip or override switch is set
- **THEN** the boot still refuses with the dedicated unattended exit code.

### Requirement: Unattended is not a research run
Unattended mode SHALL NOT be a research run: an unattended boot SHALL NOT require experiment machinery or admissibility requirements, and the six safety-net conditions SHALL be its only boot gate.

#### Scenario: No experiment configuration required
- **WHEN** an unattended boot passes all six gate conditions with no experiment or admissibility configuration present
- **THEN** the boot proceeds into the normal cycle, supervised by the live spot-supervisor.

### Requirement: Existing modes and exit codes unchanged
This change SHALL NOT alter the meaning of any existing refusal, exit code, or scenario: operator-present mode SHALL remain available and unchanged for supervised and first-run boots, exit code 2 SHALL retain today's meaning for a boot that selected neither research nor unattended mode, and research mode SHALL keep its five-condition safety net with exit code 5 on failure.

#### Scenario: Supervised boot with the operator flag
- **WHEN** a boot selects neither research nor unattended mode and runs with `KAINE_CYCLE_OPERATOR_PRESENT=1`
- **THEN** it proceeds exactly as it does today.

#### Scenario: Supervised boot without the operator flag
- **WHEN** a boot selects neither research nor unattended mode and `KAINE_CYCLE_OPERATOR_PRESENT` is not `1`
- **THEN** it refuses with exit code 2, with today's meaning.

#### Scenario: Research boot failing the net
- **WHEN** a research boot fails any of the five safety-net conditions
- **THEN** it refuses with exit code 5, with today's meaning.