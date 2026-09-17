## ADDED Requirements

### Requirement: Multi-stream observers reuse the base-class poll loop
`StreamSubscriberObserver` in `kaine/evaluation/_base.py` SHALL support a tuple of stream names and SHALL implement the poll-read-dispatch-cursor-advance loop once. Multi-stream observers (`prediction_error_observer`, `empatheia_observer`, `research_event_observer`, `welfare_observer`) SHALL inherit this behavior and SHALL NOT reimplement the loop.

#### Scenario: Base class handles multiple streams
- **WHEN** a `StreamSubscriberObserver` subclass is initialized with `streams=("a.out", "b.out")`
- **THEN** it polls both streams, advances per-stream cursors, and dispatches events without a custom `_run` method

#### Scenario: No duplicated poll loops remain
- **WHEN** `kaine/evaluation/observers/` is inspected
- **THEN** only `kaine/evaluation/_base.py` contains the generic poll loop

### Requirement: Single-stream observers continue to work unchanged
Observers that follow only one stream SHALL continue to work when the base class treats a single-element tuple as the degenerate case.

#### Scenario: Single-stream observer still functions
- **WHEN** a single-stream observer subclass is initialized with `streams=("x.out",)`
- **THEN** it behaves identically to the previous single-stream implementation
