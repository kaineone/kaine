<!-- Depends on thesis-test-configuration (the self-initiated-report policy). Implement
     AFTER that change lands. Proposal-only for now. -->

## 1. Interrupt marker on the speak intent

- [ ] 1.1 Add an `interrupt` flag to the `speak` `Intent` (payload field), default false;
  confirm it round-trips over the bus to Lingua and is ignored by non-Lingua consumers.

## 2. Cancellable / preemptable generation in Lingua

- [ ] 2.1 Change `_intent_loop` to run each generation as a held `asyncio.Task` instead of
  an inline `await`; catch `CancelledError`, discard the unspoken remainder, write a
  content-free preemption record.
- [ ] 2.2 On an interrupt-marked `speak` intent arriving mid-generation, cancel the
  in-flight task and start the new one (redirect).
- [ ] 2.3 Tests (spec `interruptible-utterance`): uninterrupted generation completes as
  before; an interrupt aborts + redirects; a partial already emitted is not un-said.

## 3. Interrupt threshold in the report policy

- [ ] 3.1 Add `interrupt_threshold` (> report_threshold) to `SelfInitiatedReportPolicy`;
  when a `speak` is in flight and a coalition crosses it with a different signature, emit
  a preempting interrupt-marked `speak` (bypass refractory, keep novelty, re-arm guard).
- [ ] 3.2 Tests: urgent surprise interrupts; below-interrupt reportworthy does not
  preempt; same-content does not interrupt.

## 4. Verification + paper

- [ ] 4.1 Suite + `lint-imports`; default (no interrupt) behavior unchanged.
- [ ] 4.2 Paper note (review-gated): interruptible/redirectable speech as a property, and
  the two-model inner-voice as the honest limit of one language organ.
