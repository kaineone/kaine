## Why

The paper (Appendix A.3) defines a categorical alert as a predictive
processor's report that meets its alert criterion, or an event another module
publishes at its alert level. The access rate's phasic input counts categorical
alerts only. In the code only the four processors set `alert` in their
payloads, so the affect module's drive crossings and emotion changes, the interoception module's fatigue and
regulation events, a failed sleep, and the held modules' alert-level events
never raise the access rate.

## What Changes

- Every event a module publishes at its alert level carries `"alert": True` in
  its payload, and every event whose intensity is chosen between the baseline
  and the alert level carries `"alert"` set to whether the alert level was
  chosen. Sites: the interoception module (`interoception.fatigue`, `interoception.regulation`), the affect module
  (`affect.drive`, `affect.emotion`, the sleep-reset `affect.state`), the sleep module
  (`sleep.sleep.completed`), Audition (`audition.transcription` and
  `audition.emotion` error events), the self-model module (`self_model.drift`) and the effectors module
  (`effectors.action`).
- The access-rate reader is unchanged: it already counts payloads with `alert`
  true.

## Capabilities

### Modified Capabilities

- `cognitive-cycle`: the phasic input counts every module's alert-level events.

## Impact

- `kaine/modules/{interoception,affect,sleep,audition,self_model,effectors}/module.py`, tests.
- Behaviour: the access rate now rises on these events as the paper specifies.
