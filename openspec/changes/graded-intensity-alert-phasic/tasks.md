## 1. Graded intensity

- [x] 1.1 the vision module, the audition module's acoustic, the sequence module: non-alert intensity `I_lo + (I_hi - I_lo) * min(1, ratio / 2)`.
- [x] 1.2 `alert` boolean on the interoception module, the sequence module and the audition module's tone payloads.

## 2. Access rate

- [x] 2.1 Phasic input from reports whose payload has `alert` true.

## 3. Tests and docs

- [x] 3.1 Intensity grades with the error ratio and saturates at the alert level; alerts take the alert level.
- [x] 3.2 A graded non-alert report at intensity 0.6 leaves the access rate at rest; an alert raises it.
- [ ] 3.3 Docs updated (in the documentation sweep).
