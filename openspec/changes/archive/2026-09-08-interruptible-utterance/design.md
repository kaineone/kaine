## Context

`thesis-test-configuration` gives the entity continuous workspace cognition (the cycle
never pauses for the language organ) and independent `think`/`speak` intents. But Lingua
realizes an utterance to completion — `_intent_loop` `await`s each `speak()`/`_produce()`
(`lingua/module.py:306,342`) — so an in-flight utterance cannot be preempted. Making it
interruptible is the piece that turns "self-initiated report" into "a mind that can
change what it's saying mid-sentence when something more important arrives."

## Goals / Non-Goals

**Goals:**
- Abort and redirect an in-flight utterance when an urgent (interrupt-threshold)
  coalition arrives.
- Keep inner thought flowing during speech (already true at the policy level).
- Behavior unchanged when no interrupt occurs (opt-in via the interrupt threshold).

**Non-Goals:**
- Simultaneous verbalization of inner monologue and outer speech — one language organ,
  one token stream. That needs a second inner-voice model (separate future change).
- Retaining or "resuming" a preempted utterance — a redirect means the entity changed
  its mind; the old line is dropped, not queued.

## Decisions

**D1 — Cancellable generation task, not inline await.** Change `_intent_loop` to launch
the generation as an `asyncio.Task` it holds a handle to, rather than `await`ing it
inline. A new interrupt-marked intent cancels that task (`task.cancel()`), the
`CancelledError` is caught, the unspoken remainder is discarded, and the new generation
starts. Rationale: minimal, idiomatic async; the loop already handles `CancelledError`
elsewhere.

**D2 — Interrupt marker on the intent, not a side channel.** Carry an `interrupt` flag on
the `speak` intent (a payload field). Rationale: the intent already flows over the bus
to Lingua; a flag keeps the decision (policy) and the mechanism (Lingua) decoupled and
testable. Only `speak` interrupts; `think` does not preempt speech.

**D3 — Two-tier-plus-interrupt thresholds in the policy.** `think_threshold <=
report_threshold < interrupt_threshold`. The interrupt path bypasses the speak refractory
(urgent) but keeps the novelty guard (don't interrupt to say the same thing) and re-arms
the in-flight guard for the new utterance.

**D4 — Content-free preemption record.** When an utterance is aborted, write only that a
preemption occurred (tick, that it was interrupted) — no partial cognitive text — matching
the zero-content policy of the other audit trails.

## Risks / Trade-offs

- **Interrupt storms** (constant preemption) → the interrupt threshold is high and the
  novelty guard prevents re-interrupting with the same content; a test asserts a
  below-interrupt moment does not preempt.
- **Cancelling mid-publish** → generation is cancelled before publish; a partial that was
  already emitted stays emitted (we do not un-say what was said), only the remainder is
  dropped. A test covers abort-before-publish.
- **Depends on `self-initiated-report`** (unmerged) → this change lands after
  `thesis-test-configuration`; its policy spec is referenced, not duplicated.

## Migration Plan

1. Add the `interrupt` marker to the `speak` intent.
2. Make Lingua's generation a cancellable task; preempt on an interrupt intent.
3. Add `interrupt_threshold` + the preempting-intent path to `SelfInitiatedReportPolicy`.
4. Tests for cancel/redirect + threshold behavior; paper note on interruptibility and the
   two-model inner-voice limit.

Rollback: set the interrupt threshold to 1.0 (unreachable) / omit it — utterances again
run to completion.

## Open Questions

- Default `interrupt_threshold` value — tuned on an observed run (pre-registered before any
  verdict).
- Whether a preempted utterance leaves any observable trace to the user beyond the
  content-free record (probably not; a redirect should read as one continuous voice).
