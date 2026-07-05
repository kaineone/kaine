## Why

KAINE's thesis is that the LLM is the **language organ, not the brain** — it
should speak *from* the conscious contents of the global workspace, conditioned
by affect, memory, percepts, and self-model. The current wiring does not do
this. Traced live during the 2026-06-03 first-boot test:

- The executive forms a `speak` intent whose `about` field is the **raw user
  utterance text** and nothing else (`kaine/workspace/volition.py:171`,
  `Intent(kind=SPEAK, about=text)`).
- Lingua realizes that intent with `self.speak(about)` and **no workspace
  snapshot** (`kaine/modules/lingua/module.py:176`). `_produce` then calls the
  LLM with `prompt=<raw utterance>`, `system=None`, `snapshot=None`
  (`module.py:191`). `make_lingua` never wires a system persona
  (`kaine/boot.py:277-291`), so `system_prompt_external/internal` are `None`.
- The **faithful renderer** — the component built precisely to turn the
  conscious coalition into text — *is* invoked, but **after** the LLM call and
  only to write the eval log (`module.py:199-200`). Its output never reaches the
  prompt.

Net effect: a spoken response is `LLM(user_text)` — a bare chatbot call with no
persona and no cognitive context. This is also why the A/B divergence
evaluation (`evaluation.ab_divergence`, sample rate 1.0) reads ~0: the "full
model" path is, today, nearly identical to the bare-LLM baseline it is supposed
to be measured against. The instrumentation is faithfully reporting that the
architecture currently makes no difference to the output.

The field has converged on how to fix exactly this, and KAINE already owns every
component required (see `design.md` for sources). The change is a **context-
assembly layer**, not a new dependency or a rewrite.

## What Changes

- Lingua SHALL assemble each LLM call's context from the conscious workspace,
  not just the triggering text. The assembled context combines four parts,
  mirroring the GWA/CoALA pattern `S = persona ∪ working-memory ∪ recalled-memory ∪ input`:
  1. **Persona (`P_self`)** — a persistent first-person system prompt, seeded
     from the Eidolon self-model (name, values, identity) and falling back to a
     minimal invariant when the self-model is empty (fresh start).
  2. **Working memory (STM)** — the faithful rendering of the current conscious
     coalition (the Syneidesis broadcast): affect, interoception, temporal
     framing, percepts, recent internal speech.
  3. **Recalled memory (RAG)** — relevant Mnemos recalls already present in the
     coalition, rendered inline.
  4. **Input** — the triggering utterance / think-cue (today's `about`).
- The faithful rendering SHALL move to **before** the LLM call and feed the
  prompt. It SHALL continue to be logged for the A/B comparison unchanged.
- Lingua SHALL acquire the current conscious snapshot without bloating the
  intent event: it maintains the latest workspace broadcast it has seen (the
  same rolling-latest pattern `audio_out` already uses for `thymos.state`) and
  renders that at speak/think time. The `speak`/`think` intent payload is
  unchanged on the wire.
- Context assembly SHALL respect a configurable token budget: cap the rendered
  coalition to the most-salient N events, drop oldest first, and never let
  assembly exceed the model's context window.
- The bare-LLM A/B baseline (`BareInferenceClient`) is **unchanged** — it
  remains the un-conditioned control. After this change the divergence metric
  becomes meaningful: it measures how much the cognitive scaffolding moves the
  output.
- The produced external-speech event SHALL carry the **triggering user input**
  in its payload. The `ab_divergence` observer is dark today because it cannot
  resolve the user text from the `lingua.external` payload (it returns early when
  `user_text` is empty — `ab_divergence.py:140`), so it can never build the bare
  baseline. Propagating the input here resurrects that observer as a side effect
  of conditioning — the full path now carries what the A/B comparison needs.
  (Privacy: this input text is internal evaluation data, written only to the
  privacy-bounded eval logs, never to the user-facing surface.)
- Privacy is preserved: the assembled context is internal. Internal speech and
  the rendered coalition SHALL NOT reach the user-facing conversation surface
  and SHALL NOT be persisted outside the existing privacy-bounded eval logs.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `lingua`: adds a requirement that external/internal speech is generated from
  an assembled cognitive context (persona + conscious coalition + recalled
  memory + input), not the bare triggering text; adds the rolling-latest
  workspace acquisition, the persona/system-prompt wiring, and the token budget.
- `faithful-renderer`: clarifies that `render_snapshot` output is a prompt input
  to Lingua (not only an eval-log artifact), and adds a stable ordering +
  salience-bounded selection requirement for that use.
- `evaluation-sidecar`: the external-speech event carries the triggering user
  input so the `ab_divergence` observer can resolve it and build the bare
  baseline (it previously returned early on empty `user_text`).
