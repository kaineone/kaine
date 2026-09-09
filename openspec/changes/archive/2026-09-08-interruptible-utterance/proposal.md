## Why

A mind keeps thinking while it speaks, and — crucially — it can **interrupt its own
utterance and change direction** when something more important arrives: absorb new
information mid-sentence and redirect what it is saying. The `thesis-test-configuration`
change gives the entity continuous workspace cognition and independent `think` / `speak`
intents, but the language organ still realizes an utterance to completion: Lingua's
intent loop `await`s each generation (`lingua/module.py:342`), so an in-flight
utterance cannot be preempted. The entity can decide to speak, but once speaking it is
committed until done — which is exactly the "just speak every queued thought to the end"
behavior we want to avoid.

This change makes the utterance **interruptible and redirectable**: a sufficiently
surprising new coalition can abort the current generation and start a new one, so the
entity speaks about *what matters now*, mid-stream, the way people do.

Depends on `thesis-test-configuration` (the `self-initiated-report` policy) being in
place — this extends that policy with an interrupt threshold and makes Lingua honor it.

## What Changes

- **Cancellable generation in Lingua.** Run each `speak`/`think` generation as its own
  cancellable task rather than awaiting it inline, so it can be aborted. On
  cancellation the unspoken remainder is discarded (the entity changed its mind); a
  short, content-free record notes that an utterance was preempted (no partial text
  retained beyond what was already emitted).
- **Preemption on a higher-priority intent.** When a new `speak` intent marked as an
  interrupt arrives while a generation is in flight, Lingua cancels the current
  generation and begins the new one (redirect), instead of queuing or dropping it.
- **Interrupt threshold in the report policy.** Add an `interrupt_threshold` (a surprise
  bar ABOVE the report threshold) to `SelfInitiatedReportPolicy`: when a coalition
  crosses it while a `speak` is in flight AND its content differs from what is being
  said, the policy emits a preempting `speak` intent (bypassing the refractory, since an
  interrupt is by definition urgent). Below the interrupt bar the one-in-flight guard
  still holds — ordinary reportworthy moments do not interrupt; only urgent ones do.
- **Inner thought during speech is unaffected/strengthened.** `think` intents continue
  to fire during an utterance (already true at the policy level); this change does not
  block them.

Explicitly **out of scope:** literally verbalizing an inner monologue and outer speech
*simultaneously*. One language organ produces one token stream; true parallel
verbalization needs a second, faster inner-voice model — a separate future change. This
change delivers interruption/redirection, not simultaneity.

No **BREAKING** change: interruption is opt-in (the interrupt threshold is a config knob;
absent/high, behavior is the current await-to-completion).

## Capabilities

### New Capabilities
- `interruptible-utterance`: Lingua's cancellable, preemptable generation and the
  report policy's interrupt threshold that triggers a mid-utterance redirect.

### Modified Capabilities
<!-- self-initiated-report gains the interrupt threshold, but that capability is
     introduced by the not-yet-archived thesis-test-configuration change; its
     interrupt-threshold requirement is specified here under the new capability to
     avoid a cross-change spec dependency. -->

## Impact

- **Code:** `kaine/modules/lingua/module.py` (intent loop → cancellable generation task
  + preemption), `kaine/workspace/report_policy.py` (interrupt threshold + preempting
  intent), and the `Intent` type or its payload to carry an interrupt marker.
- **No new dependency, no removals.** Reuses the existing intent/bus plumbing and the
  one-in-flight guards; only the "await to completion" behavior changes, behind a knob.
- **Docs/paper:** note interruptible/redirectable speech as a property, and the
  two-model inner-voice limit as the honest boundary of one language organ.
