## 1. Backend

- [x] 1.1 `WetwareOscillator.step` passes a monotonically increasing step counter as the exchange tag. It appends a sample only when the returned observation carries a tag not recorded before.

## 2. Tests

- [x] 2.1 In beat mode, a module that publishes once every several ticks records the evoked response to strong drive, not background firing.
- [x] 2.2 Before any response exists, a step records nothing, and a response read twice is recorded once.
- [x] 2.3 Existing oscillator tests still pass; their broker stubs return real observations.

## 3. Docs

- [x] 3.1 docs/cl1.md: once the substrate follows the cycle, each oscillator sample is the response to the module's previous publish.
