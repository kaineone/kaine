## ADDED Requirements

### Requirement: Cancellable utterance generation

Lingua SHALL run each `speak` / `think` generation as a cancellable task rather than
awaiting it inline, so an in-flight utterance can be aborted. On cancellation the
unspoken remainder SHALL be discarded and a short, content-free record SHALL note that
an utterance was preempted; no partial text beyond what was already emitted is retained.

#### Scenario: In-flight generation can be aborted

- **WHEN** a generation is in flight and a cancellation is requested
- **THEN** the generation stops, the unspoken remainder is not published, and a
  content-free preemption record is written

#### Scenario: Uninterrupted generation completes normally

- **WHEN** a generation runs with no interrupt arriving
- **THEN** it completes and publishes exactly as before this change

### Requirement: Preemption redirects to the new utterance

Lingua SHALL, when a `speak` intent marked as an interrupt arrives while a generation is
in flight, cancel the current generation and begin the new one (redirect), rather than
queuing it behind the current utterance or dropping it.

#### Scenario: Interrupt intent redirects mid-utterance

- **WHEN** an interrupt-marked `speak` intent arrives during an in-flight generation
- **THEN** Lingua aborts the current generation and starts generating the new intent

### Requirement: Interrupt threshold above the report threshold

The self-initiated report policy SHALL expose an `interrupt_threshold` set ABOVE the
report threshold. When a coalition's precision-weighted surprise crosses the interrupt
threshold while a `speak` is in flight AND the coalition's content signature differs
from what is being said, the policy SHALL emit a preempting (interrupt-marked) `speak`
intent, bypassing the ordinary refractory (an interrupt is urgent by definition).

#### Scenario: Urgent surprise interrupts

- **WHEN** a `speak` is in flight and a new coalition crosses the interrupt threshold
  with a different content signature
- **THEN** the policy emits an interrupt-marked `speak` intent for the new coalition

### Requirement: Ordinary reportworthy moments do not interrupt

A coalition that clears the report threshold but not the interrupt threshold SHALL NOT
preempt an in-flight utterance; the one-in-flight guard still holds. Only urgent
(interrupt-threshold) surprise interrupts.

#### Scenario: Below-interrupt surprise waits its turn

- **WHEN** a `speak` is in flight and a new coalition clears the report threshold but not
  the interrupt threshold
- **THEN** no preempting intent is formed; the current utterance is allowed to finish
