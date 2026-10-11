## MODIFIED Requirements

### Requirement: Deep consolidation with global activation downscaling
Hypnos phase 2 SHALL first replay traces of the wake just ended inside a replay
window during which external perception is suspended, and SHALL then call
Mnemos's `downscale` with the replayed traces as the protected set (paper
A.10). The phase metadata SHALL record the downscaling summary: the traces
stored since the previous sleep, the factor, the number protected, the number
silent, and the total strength before and after. `downscale` SHALL run even
when replay fails, with nothing protected. `[hypnos.consolidation].downscale_factor`
SHALL NOT be accepted.

#### Scenario: Downscaling preserves ordering
- **WHEN** downscaling is applied
- **THEN** every unprotected trace's strength is reduced by the same factor and
  their ordering by strength is unchanged

#### Scenario: Perception is suspended during replay window
- **WHEN** the phase-2 replay window is open
- **THEN** live external perception capture is suspended for its duration and
  restored afterward

#### Scenario: The old factor key fails the boot
- **WHEN** `[hypnos.consolidation]` sets `downscale_factor`
- **THEN** the Hypnos factory raises a configuration error
