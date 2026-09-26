# nous-wetware-backend Specification

## Purpose
Nous on the CL1 substrate as a hybrid: KAINE's own active-inference engine keeps beliefs and expected free energy, and the substrate proposes the policy, in a shadow mode that changes nothing or a drive mode that acts on the proposal.

## Requirements

### Requirement: The tissue proposes Nous' policy beside the silicon engine
When `nous = "cl1"`, the plugin SHALL wrap KAINE's own Nous engine. Each step SHALL run the silicon engine first, stimulate one channel group per action with an amplitude that rises as that action's expected free energy falls, and decode the tissue's proposed action as the group with the highest per-channel firing in the returned window, ties and silent windows going to the silicon choice. The returned window SHALL be the response to Nous' own most recent stimulation, never a later window that carried none of it, and the tissue's answer SHALL be scored against the silicon choice that stimulation encoded.

#### Scenario: Response one step later once the substrate follows the cycle
- **WHEN** the substrate follows KAINE's cycle and Nous steps less often than the cycle ticks
- **THEN** each step reads the response window to Nous' previous stimulation, labelled with the silicon choice that stimulation encoded, and scores the answer against that choice

#### Scenario: Proposal follows the encoded preference on the reference culture
- **WHEN** the silicon engine's EFE strongly favours one action for many steps on the simulator's reference culture
- **THEN** the tissue's proposal agrees with that action on most of those steps

### Requirement: Shadow mode never changes Nous' behaviour
In `mode = "shadow"` (the default), every returned result SHALL equal the silicon engine's result, and the tissue's proposal and the running agreement rate SHALL only be logged.

#### Scenario: Shadow result
- **WHEN** the tissue proposes a different action from the silicon engine in shadow mode
- **THEN** the returned `action_index` and `action` are the silicon engine's

### Requirement: Drive mode acts on the tissue's proposal
In `mode = "drive"` the returned `action_index` and `action` SHALL be the tissue's proposal, with beliefs and EFE unchanged, and the plugin SHALL log a WARNING on every boot that the tissue drives Nous' policy.

#### Scenario: Drive result
- **WHEN** the tissue proposes action 2 and the silicon engine chose action 0 in drive mode
- **THEN** the returned `action_index` is 2 and `posterior` and `policy_efe` equal the silicon engine's

### Requirement: Feedback follows agreement
Each step SHALL stimulate the feedback channels predictably (a fixed pulse on both) when the previous tissue answer agreed with the silicon choice it encoded, and unpredictably (a seeded random amplitude per channel) when it did not, a silent or tied window counting as a disagreement.

#### Scenario: Agreement then disagreement
- **WHEN** one step's proposal agrees and the next disagrees
- **THEN** the step after the first carries the fixed feedback pulse and the step after the second carries the random one

### Requirement: Failures and optional engine methods pass through
A silicon result that timed out or errored SHALL be returned unchanged with no stimulation, and any attribute the wrapper does not define SHALL be forwarded to the inner engine.

#### Scenario: Revive seeding
- **WHEN** Nous calls `seed_posterior` on the wrapped engine after a revive
- **THEN** the call reaches the inner engine and returns its result

### Requirement: Synchronous substrate windows run one at a time
Before the substrate follows KAINE's cycle, each step runs its own substrate window. The broker SHALL serialise those windows, and the switch to following the cycle, across threads, because Nous steps its engine in a worker thread while other converted modules step on the event loop.

#### Scenario: Nous and Chronos step at once before the first tick
- **WHEN** Nous' worker thread and Chronos on the event loop each exchange with the broker before the first cycle tick
- **THEN** their windows run one after the other on the substrate, never interleaved

### Requirement: Following the cycle never blocks KAINE's event loop
When KAINE's first cycle tick finds a synchronous substrate window in flight, the plugin SHALL NOT wait for it on the calling thread: it SHALL finish the switch to following the cycle on a background thread and skip ticks until the switch completes. Closing the plugin SHALL wait for a pending switch before stopping the substrate.

#### Scenario: First tick during a Nous window
- **WHEN** the first cycle tick arrives while Nous' worker thread is running a synchronous window
- **THEN** the tick returns without waiting, and the substrate follows the cycle once that window ends
