# Design

## Context

The module-ignition study runner (`kaine/study/`) already implements: line isolation per step (working directory, bus db, collection prefix), the step loop with preservation at film end, the four-film manifest, the dry-run harness, the compose service, and the disk guard. The existing runner generates a branching plan (seed → branch 0…9, repeat, accumulate 1…9) and its analysis compares branches against each other and against the noise reference.

The conversion simplifies the plan generator and analysis while keeping the runner's step execution unchanged.

## Goals / Non-Goals

**Goals:**
- Replace the branch/repeat/accumulate plan with a progressive linear sequence
- Keep the step execution, recording, preservation, and compose infrastructure intact
- Add `broadcast_capacity` as a configurable parameter for the K=1 decision
- Adapt the analysis to step-over-step comparisons
- Support the development run with a dry run before the real run

**Non-Goals:**
- Changing the entity's cognition, the workspace, or any module
- Building the content-workspace-level (separate change)
- Automating module addition mid-run (each step is a separate revive)
- Removing the study runner code; it is refactored, not deleted

## Decisions

### D1. Progressive plan replaces the branch grid

The plan generator produces:
```
step 0: seed (gestation → maturation → preserve)
step 1: revive seed + [episodic-memory] → films → preserve
step 2: revive step 1 + [world-model] → films → preserve
...
step N: revive step N-1 + [last-module] → films → preserve
```

Each step is a dict with `kind` ("seed" or "progressive"), `step_index`, `modules` (full set), `modules_added` (delta), and `start_bundle` (path to previous step's preservation).

**Alternative rejected:** keeping branches as a subset (branch 0 only). This preserves dead code for the noise reference and accumulate lines.

### D2. Module order from configuration

The module addition order is declared in the development-run profile (`config/profiles/development-run.toml`):
```toml
module_order = [
    "episodic-memory",
    "world-model",
    "planning",
    "self-model",
    "social-cognition",
    "vocal",
]
```

The base set (interoception, sequence, vision, audition, language, workspace, action-selection, affect, sleep) is always present. Each step adds the next module from `module_order`.

### D3. broadcast_capacity parameter

The profile includes `broadcast_capacity` (default: from shipped config). The runner's overlay sets `[workspace].broadcast_capacity` for every step. This lets the CTO choose K at run init time without changing the shipped default.

### D4. Step-over-step analysis

The analysis computes for each adjacent pair (step k, step k-1):
- ignition rate (broadcasts per tick)
- coalition membership distribution (which modules appear in winning coalitions)
- new-module ignition rate (how often the newly added module appears in a coalition)
- content-free divergence metrics (reusing the existing analysis functions)

The branch-vs-branch, branch-vs-repeat, and accumulate-vs-branch comparisons are removed.

### D5. Dry run stays mandatory

Before the real run, a dry run with a tiny stand-in programme verifies end-to-end: plan generation, step execution (faked cycle), manifest writing, preservation, revive-with-extra-module, analysis. This is the existing dry-run harness adapted to progressive steps.

### D6. The old study's real run (task 2.5) is superseded

Task 2.5 in the module-ignition-study (the real branching run) is superseded by the development run. The runner code for branches is removed, not deprecated.

## Risks / Trade-offs

### R1. No controlled comparison
The branching protocol compared the effect of each module against the same baseline (the seed). The progressive protocol loses this: each step differs from the previous by one module AND by the experience of the previous viewing. This is accepted; the CTO chose development over measurement.

### R2. No noise floor
Without the repeat step, there is no estimate of how much two identical runs diverge. Mitigation: the step-over-step analysis can flag anomalously large deltas, and the operator can add a repeat step later if needed.

### R3. Runner refactoring scope
The plan generator, plan validator, and analysis all change. The step execution does not. Testing must cover the new plan shape end to end.
