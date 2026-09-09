## Why

The base thesis is Baars' global workspace joined to predictive processing:
specialized predictive processors compete, precision-weighted, for a shared
workspace; the winning coalition is broadcast back to all of them and becomes the
context they predict against next; and the mind is that competition-and-broadcast,
not any single module and not a system where input is piped to a language model.

The reference implementation drifted from that in two ways that make the thesis
untestable:

1. **The paper's "minimal" set (Soma + Chronos + Lingua) is too thin** to exercise
   competition — two internal channels, no external world — and the offline
   ablation on it leans NULL for want of anything rich to arbitrate.
2. **A speech-to-text path survives** (`audition.transcription` → a Volition
   "answer the utterance" speak intent). Any path that lets a transcript reach the
   language organ lets the LLM ride the text and **confounds the one experiment
   meant to falsify the thesis** — it can no longer tell "the competitive
   workspace did the work" from "the model answered a prompt." That is a chatbot
   with a workspace decoration.

This change configures the system into the honest, falsifiable base-thesis form —
**by gating, not deletion** (every built module and code path is preserved, just
switched off or bypassed until the base thesis is proven or disproven).

## What Changes

- **Thesis-test module set (config).** Enable exactly the diverse predictive
  processors the thesis needs — **Soma** (interoception), **Chronos** (time),
  **Topos** (foveated vision over raw video), **Audition** (raw sound as prediction
  error) — plus the always-on **Syneidesis** (workspace) and **Volition** (action),
  and **Lingua** as the output-only voice. Everything else (Mnemos, Eidolon,
  Thymos, Phantasia, Empatheia, Nous, Vox, Hypnos, Praxis, Perception/Mundus, the
  oscillatory layer) stays built and toggled OFF.
- **Perception as prediction error (STT-ectomy).** A gate so Audition, when
  disabled for transcription, publishes only `audition.perception` (acoustic
  prediction error), `audition.emotion`, and `audition.prosody` — never
  `audition.transcription`. The entity hears the *sound* of speech, not a
  transcript. The STT code is preserved, only bypassed.
- **Self-initiated report gate (new Volition policy).** With the chatbot trigger
  removed and Thymos off, nothing would make the entity speak. Add an injectable
  action-selection policy that forms `think` / `speak` intents from the entity's
  OWN state — a report threshold ABOVE the conscious (publication) threshold,
  gated by precision-weighted surprise, novelty, a refractory interval, and the
  existing one-in-flight guards. The entity speaks rarely, about the present, only
  when something genuinely violates its predictions — never a stream, never a
  stale queue.

No **BREAKING** change: the new policy and STT gate are opt-in; default behavior
is unchanged; nothing is removed.

## Capabilities

### New Capabilities
- `self-initiated-report`: the surprise-gated, refractory, self-initiated
  `think`/`speak` action-selection policy (the "report or stay silent" decision
  driven by the workspace's own precision-weighted competition, not by input).
- `thesis-test-configuration`: the gated run configuration (module toggle set +
  live raw-AV perception feed + foveation + STT off + the report policy) that
  instantiates the base-thesis form for a bootable, falsifiable entity.

### Modified Capabilities
- `audition-predictive`: adds a requirement that transcription is gateable, so
  audio can enter the workspace only as prediction error (no transcript path).

## Impact

- **Code:** new `kaine/workspace/report_policy.py`; a transcription gate in
  `kaine/modules/audition/module.py`; Volition policy selection in
  `kaine/cycle/__main__.py`; a new `config/profiles/thesis_test.toml`. Reuses the
  existing `[modules]` toggles, the injectable `ActionSelectionPolicy` seam, the
  one-in-flight guards, and the perception feed.
- **No removals / no deletions:** every module and the STT code remain; this is
  configuration + one new injectable policy.
- **Docs/paper:** the paper's minimal-set and audio-input framing are updated to
  the base-thesis form (separate, review-gated; a paper-agent prompt accompanies
  this change).
