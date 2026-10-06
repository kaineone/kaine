## Context

Prior work this change builds on and does not redo:

- `2026-06-07-chronos-forward-model` built the forward-prediction head, its online adaptation and its sleep suspension.
- `2026-06-07-fix-chronos-user-input-stream` fixed the user-input stream name and added the stream-wiring test.
- The Chronos reservoir-seed requirement made the network itself survive preservation.

## Decisions

### D1. What counts as an interaction

An interaction is someone speaking to the entity on an operator channel. Chronos counts it from `audition.out` events whose type is speech-path (`audition.transcription` with non-empty text, or `audition.emotion`) and whose `source_label` is an operator source.

- Volition and Empatheia already draw the same line between operator channels and media. They each hold a copy of the list today. This change moves it to one shared constant, so the three can never disagree.
- `audition.emotion` is needed because base-thesis turns transcription off, and emotion is then the only speech-path event.
- An emotion event that reports an error still means speech was detected, so it counts.
- A loudspeaker near the live microphone will count as operator speech. Volition and Empatheia have the same limitation, and fixing it needs speaker identification, which is out of scope.

### D2. Featurizer layout versioning

- The layout is a small integer held by the featurizer, and Chronos records it in `serialize()`.
- `deserialize()` sets the featurizer to the recorded layout, or to layout 1 when the key is absent.
- A Chronos that never receives state uses the newest layout.
- Featurizing reads the layout on every call, so the order of `initialize()` and `deserialize()` does not matter.
- An unknown layout number in a snapshot is a load error. It is never silently mapped to another layout.

Layout 2 uses slot 23 rather than a 25th dimension.
- Keeping the length at 24 means no network, head or plugin input changes shape.
- The existing comment on slot 23 warns that populating it needs a coordinated retrain. Versioning provides exactly that: no trained being ever sees slot 23 change meaning.

### D3. Time since the last interaction before any interaction

The spec reports `inf` until the first interaction, and Thymos ignores `inf`, so the social drive stays at its baseline until someone first speaks. This change keeps that behaviour. Raising the social drive from isolation since spawn would be a new affect rule, and it belongs in a Thymos change with its own citation, not here.

## Risks

- Turning the head on in base-thesis changes Chronos's salience, and so changes the workspace competition in the next study. That is the intended paper-parity fix. It needs re-baselining before a study and is recorded in the research impact.
- Layout 1 beings keep the Praxis/Audition overflow conflation. That is the price of not altering a trained being. It is logged once at revive.
