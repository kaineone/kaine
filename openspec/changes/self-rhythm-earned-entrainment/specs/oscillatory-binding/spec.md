## MODIFIED Requirements

### Requirement: Spike-to-phase converter with minimum population and window guards
The phase estimator SHALL convert binned spike rates to instantaneous phase using
`scipy.signal.hilbert`. The oscillator population SHALL have at least 16 units and
the PLV window SHALL span at least 10 samples; these SHALL be enforced at
configuration time. The v1 implementation drives oscillators from module
co-activity (publish rate) as a proxy for the paper's content-relatedness; this
approximation SHALL be noted as a limitation in the design document alongside a
v2 sketch (driving LIF from prediction-error magnitude). The self-rhythm oscillator's
phase, which Soma reads interoceptively, SHALL be taken from its population rate
band-limited to its own physiological band over a window of at least 4 s, not from the
last sample of an unfiltered short window.

#### Scenario: Locked populations yield PLV near 1
- **WHEN** two populations of ≥ 16 units share the same spike train over ≥ 10
  samples
- **THEN** the computed PLV is ≥ 0.95

#### Scenario: Independent populations yield PLV near 0
- **WHEN** two populations of ≥ 16 units spike independently (Poisson, uncorrelated)
  over ≥ 10 samples
- **THEN** the computed PLV is ≤ 0.2

#### Scenario: The self-rhythm phase follows its slow rhythm
- **WHEN** the self-rhythm oscillates at its intrinsic frequency in band
- **THEN** its reported phase advances at that frequency rather than at the units' firing rate
