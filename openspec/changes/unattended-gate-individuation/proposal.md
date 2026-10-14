## Why

The unattended-boot spec says an unattended start evaluates the research
safety net through the same evaluator, with identical predicates. When the
gate was built the net had five checks, and the gate mapped all five to its
conditions 1 to 5. The individuation rebuild (#331) then added a sixth check
to the net, `individuation_enabled`, so that a research entity's protection
does not rest on the secondary divergence signals alone. The unattended gate
was not extended. `conditions_from_safety_net` still reads five keys, so an
unattended start passes with the individuation producer off, and the book now
records that gap as if it were a rule ("The individuation requirement applies
to research mode only").

An entity running with nobody present needs that protection at least as much
as a research entity does. This change restores the invariant the spec already
states: the unattended gate covers every condition of the research net.

## What Changes

- The unattended gate gains condition 9, "individuation wired", taken from the
  research net's existing `individuation_enabled` check. The predicate is not
  changed: `[individuation].enabled`, a valid `[individuation]` section, and
  the `language` module enabled.
- Conditions 6 to 8 keep their numbers, so the `checks` keys recorded in
  runtime.json, the incident log and the dashboard do not move.
- The condition checks that the individuation producer will run. It does not
  require the entity to have individuated.
- Condition 7 (the caretaker start notice) already runs only when every other
  condition has passed, so it now waits on condition 9 as well.
- A test asserts that every check the research net's evaluator returns maps
  to an unattended condition, so the next check added to the net cannot be
  left out without a failing test.
- Docs and the dashboard run-identity label say nine conditions, and the exit-6
  row of the refusal table is pinned by the docs test.

## Capabilities

### Modified Capabilities

- `unattended-boot`: the gate covers every research-net condition, adding
  condition 9 (individuation wired).

## Impact

- Code: `kaine/cycle/unattended_gate.py`, docstrings in
  `kaine/cycle/__main__.py`, the label in
  `kaine/dashboard/templates/_run_identity.html` and `kaine/dashboard/static/dashboard.js`.
- Tests: `tests/test_unattended_gate.py`, `tests/test_unattended_integration.py`,
  `tests/test_unattended_docs.py`,
  `tests/test_cycle_entrypoint.py`.
- Docs: the unattended sections of the book and the exit-code table, and
  the condition list in the header of `quadlet/kaine-cycle-unattended.container`.
- Behaviour: an unattended start with `[individuation]` disabled or the language module off
  now refuses with exit 6. Operator-present and research boots are unchanged.
