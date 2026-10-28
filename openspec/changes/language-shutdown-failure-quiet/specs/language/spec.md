## ADDED Requirements

### Requirement: A stop interrupts the utterance in flight
Once a stop has begun, meaning the cycle's stop event or the language module's own stop flag is set, the language module SHALL treat a speak or think generation that is cancelled, fails or answers as interrupted. It SHALL discard any answer that arrives after the stop began (nothing is logged to the intent log or published). It SHALL log at most one INFO line naming the intent kind and, for a failure, the exception class, with no traceback. For an external (`speak`) utterance it SHALL write one content-free `interrupted_by_stop` record to `language.internal` whose payload contains only `mode` and `reason_class` (the exception class name, `CancelledError` for a cancellation, or `shutdown` for an answer discarded after the stop began). For a `think` it SHALL write no record. The record SHALL replace `realization_failed` when a stop has begun. A module rebuilt by the supervisor SHALL receive the same stop event.

#### Scenario: The model server goes away after the stop signal
- **WHEN** the cycle's stop event is set and an in-flight speak request then raises a connection error
- **THEN** one INFO line names `speak` and `ConnectionError`, no warning, error or traceback is logged, `language.internal` receives one `interrupted_by_stop` record `{"mode": "speak", "reason_class": "ConnectionError"}` and no `realization_failed`

#### Scenario: The module shuts down during a speak
- **WHEN** the module shuts down while a speak generation is in flight
- **THEN** the generation is cancelled, nothing is published on `language.external`, and one `interrupted_by_stop` record with `reason_class` `CancelledError` is written

#### Scenario: An inner thought is cut
- **WHEN** a stop begins during a think and the generation fails or is cancelled
- **THEN** no record is written

#### Scenario: The organ answers after the stop began
- **WHEN** the stop event is set while a speak request is in flight and the organ then answers normally
- **THEN** the answer is not logged or published and one `interrupted_by_stop` record with `reason_class` `shutdown` is written

#### Scenario: A failure while running
- **WHEN** a speak or think request raises while no stop has begun
- **THEN** an ERROR record with the traceback is logged and one `realization_failed` record is written, and no `interrupted_by_stop` record
