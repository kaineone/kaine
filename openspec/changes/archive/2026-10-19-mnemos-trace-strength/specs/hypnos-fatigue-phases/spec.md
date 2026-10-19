## MODIFIED Requirements

### Requirement: Deep consolidation with global activation downscaling
The sleep module's phase 2 SHALL first replay traces of the wake just ended inside a replay
window during which external perception is suspended, and SHALL then call
the episodic memory module's `downscale` with the replayed traces as the protected set, which
downscales and then prunes (paper A.10). The phase metadata SHALL record the downscaling summary: the traces
stored since the previous sleep, the factor, the number protected, the number
pruned at the floor and for the budget, the total strength before and after
the scaling, and the store size after pruning. When replay fails,
phase 2 SHALL skip the downscaling and pruning for that sleep and record
`downscale_skipped`; the wake's traces stay in the next sleep's pool. Replay SHALL run inside
a replay window that the sleep module opens through the episodic memory module immediately
before calling `replay_now()` and closes once replay returns or raises.
`[sleep.consolidation].downscale_factor` SHALL NOT be accepted.

#### Scenario: Downscaling preserves ordering
- **WHEN** downscaling is applied
- **THEN** every unprotected trace's strength is reduced by the same factor and
  their ordering by strength is unchanged

#### Scenario: Replay precedes downscaling
- **WHEN** phase 2 runs with the episodic memory module present
- **THEN** `replay_now()` is called before `downscale()`

#### Scenario: Perception is suspended during replay window
- **WHEN** the phase-2 replay window is open
- **THEN** live external perception capture is suspended for its duration and
  restored afterward

#### Scenario: The old factor key fails the boot
- **WHEN** `[sleep.consolidation]` sets `downscale_factor`
- **THEN** the sleep module's factory raises a configuration error

#### Scenario: A failed replay skips downscaling
- **WHEN** `replay_now()` raises in phase 2
- **THEN** `downscale` is not called, the phase reports the error, and its
  metadata records `downscale_skipped`
