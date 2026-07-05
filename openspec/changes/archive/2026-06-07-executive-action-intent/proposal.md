## Why

The architecture's central safeguard — *"a winning coalition must clear a
publication threshold before reaching the action layer ... the system can
consider speaking and decide that silence is the better choice"* (paper §37),
with disinhibition explicitly listed as the failure mode prevented by
*"executive inhibition in Syneidesis"* (§147) — **is not enforced anywhere.**
Syneidesis computes `WorkspaceSnapshot.inhibited` and the cycle broadcasts it,
but no effector consumes it: Lingua and Praxis decide to act on their own. There
is **no action layer** between consciousness (the broadcast) and the effectors.
The recently-rejected reflexive turn-loop (Lingua replying to any heard
utterance) was a direct symptom of this missing layer.

This change builds the missing layer: the entity makes an explicit, inhibition-
respecting **decision to act**, expressed as an *intent*, which effectors then
realize. The LLM is kept as a language *organ* that speaks when the executive
decides to speak — not a reflexive responder.

## What Changes

- **New executive action-selection step ("Volition")** run by the cognitive
  cycle immediately after each experiential broadcast. It:
  - emits **nothing** when `snapshot.inhibited` is true (the coalition did not
    clear the publication threshold → silence). This structurally enforces
    executive inhibition for *all* effectors at once.
  - otherwise applies an action-selection policy over the conscious coalition
    (and, in later changes, motivational state) and emits zero or more
    **intent** events to a `volition.out` stream — e.g. `{kind: "speak",
    about: <ref to coalition content>}`.
- **Lingua becomes intent-driven, not reflexive.** It realizes `speak` intents
  (subscribes to the intent stream) via its existing `speak()` path → external
  speech. It no longer self-triggers on user input. (Internal speech / `think`
  remains available for deliberation, triggerable by a `think` intent.)
- **Praxis becomes intent-driven.** Effector execution happens only in response
  to an `act` intent from the executive; Praxis never acts on a raw broadcast.
- **Inhibition is enforced structurally:** because intents originate only from
  the Volition step, and that step is silent when inhibited, nothing reaches any
  effector while the entity is inhibited.
- **v1 action-selection policy is deliberate but minimal and pluggable:** it
  produces a `speak` intent when the non-inhibited conscious coalition contains
  content the entity is disposed to respond to. Drives biasing this policy
  (`drives-to-behavior`) and recalled context informing it (`spontaneous-recall`)
  land as separate changes that plug into the same decision point.

## Capabilities

### New Capabilities

- `action-selection`: the executive decision layer that, gated by Syneidesis's
  publication threshold, turns conscious content into explicit action intents
  that effectors realize.

### Modified Capabilities

- `lingua`: external speech is produced only in response to a `speak` intent
  from the executive; Lingua does not self-trigger on perceived input.
- `praxis`: effectors execute only in response to an `act` intent; Praxis does
  not act directly on the broadcast.

## Impact

- **Code**: new `kaine/workspace/volition.py` (or `kaine/cycle/`) action-selector
  + intent types; cycle wiring to invoke it post-broadcast; Lingua intent
  subscription; Praxis intent routing. New `volition.out` stream (added to the
  canonical producer set + the wiring test).
- **Tests**: unit tests for the inhibition gate (no intent when inhibited),
  policy output, and intent realization by Lingua/Praxis — all with fakes, no
  live boot.
- **Docs/specs**: new `action-selection` spec; `lingua`/`praxis` deltas.
- **Follow-ons**: `drives-to-behavior` and `spontaneous-recall` extend the
  policy / inputs at this same decision point.
