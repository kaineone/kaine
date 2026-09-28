## Why

Nous selects actions by expected free energy, and it learns their consequences (`nous-learned-agency`). But nothing acts on its choices. It publishes an unsigned `intent.act` on `nous.out`, a stream no effector reads, and the Hypnos ignition audit counts these intents as unrealizable. The operator has decided (2026-09-28, ignition-study task 1.11) that Nous's choices SHALL drive real actions through the existing executive gates.

This matches the design of record:
- **The pymdp swap** (2026-06-07) specified that Nous's actions become intents "through the existing Volition/intent path … never as a direct effector call — keeps the two-layer safety gates in charge". It also says "Nous proposes; the executive path disposes."
- **The papers.** Paper v4 describes Nous as selecting "policies (action sequences)". The current manuscript routes "the report-or-act decision governed … by expected free energy" through "a distinct action layer": Volition, "the only path from a conscious snapshot to an effector".
- **The ONA version** only deferred action.
- **#249's "Nous never acts"** was a degenerate-model finding, since fixed, not a decision.

Three defects stand in the way:
1. Nous emits its proposals even on inhibited ticks.
2. `request_maintenance` does nothing, although a code comment says it signals Hypnos through Soma.
3. Nous learns as if every selected action happened, whether or not anything realized it.

## What Changes

- **Nous proposes; Volition disposes.**
  - Nous stops emitting its own unsigned `intent.act`. It publishes a content-free `nous.proposal` (`proposal_id`, `action`, `kind` ∈ {think, speak, rest}, `step`) on `nous.out`.
  - A Volition proposal source acts on a proposal only when the proposal has won workspace competition, i.e. it is in the conscious coalition of a non-inhibited experiential broadcast. A choice that never becomes conscious is never acted on.
  - Realization uses the existing guards: the inhibition gate, one speak and one think in flight, the refractory periods, and no self-response.
  - `think` and `speak` become ordinary `volition.out` intents that Lingua realizes. No Nous action is a Praxis effector action; Praxis and its empty-by-default whitelist are untouched.
- **Maintenance becomes a real rest request.**
  - `rest` proposals become a new Volition intent kind, `rest`, on `volition.out`. Hypnos honours it as a sleep request through the same lock and guards as its fatigue and regulation triggers.
  - A minimum interval between requested rests is measured in entity time (`[hypnos].requested_rest_min_interval_s`). Hypnos's non-interruptibility, bounded deferral and operator-freeze preemption are unchanged.
  - An exploring Nous therefore cannot cause a sleep storm.
- **Nous learns from the action actually taken.**
  - Volition publishes a content-free `volition.proposal_outcome` (`proposal_id`, `realized`, `reason`) for every proposal it sees.
  - Before its next step, Nous records the taken action: the proposed action if realized, `no_op` otherwise (declined, inhibited, guarded, rate-limited, or never conscious).
  - An outcome that arrives after the next step is counted and not applied.
- **Provenance and audit.**
  - Intents that realize a proposal carry `origin: "nous"`.
  - The ignition audit gains a `nous_initiated` category, and counts proposals that were not taken and `rest` realizations (`hypnos.sleep.started` with a Nous-origin request).
  - The "unrealizable intents on `nous.out`" figure stays as a guard that should read zero, because Nous no longer emits intents.
- **Switch and record.**
  - `[nous].drive_actions` (default `true`, the operator's decision) turns the proposal source on. `false` keeps Nous observational, for ablation.
  - Every run's identity records the value, because it changes what Nous's learned transitions mean.
  - The base-thesis profile keeps Nous disabled, so no new path turns on there.

## Capabilities

### Modified Capabilities
- `nous-active-inference`: Nous proposes through `nous.proposal` and learns from the action actually taken.
- `action-selection`: Volition realizes conscious Nous proposals under the existing gates, and adds the `rest` intent kind.
- `hypnos`: honours a rate-limited rest request from Volition.
- `hypnos-consolidation`: the ignition audit accounts for Nous-originated realizations.

## Impact

- **Changed:**
  - `kaine/modules/nous/module.py` (proposal events; the taken-action feedback; the false maintenance comment);
  - the Volition policy composition in `kaine/workspace/` and its wiring in `kaine/cycle/__main__.py`;
  - `kaine/modules/hypnos/module.py` and `ignition_audit.py`;
  - `kaine/modules/lingua/module.py` (ignores `rest`);
  - the event taxonomy (`kaine/evaluation/observers/research_event_observer.py`);
  - the FaithfulRenderer templates, config, docs and tests.
- **Unchanged:**
  - Praxis and its whitelist;
  - HMAC signing of `act` intents;
  - the inhibition gate;
  - gestation dormancy (Vox holds speech while dormant);
  - the base-thesis profile;
  - every welfare and preservation monitor.
