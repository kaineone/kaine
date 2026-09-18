# Design — Conditioning the Language Organ on the Conscious Workspace

## 1. Problem, precisely

Today's speak path (verified live 2026-06-03):

```
audio_in transcription ──► Syneidesis selects it into the conscious coalition
                            (WorkspaceSnapshot.selected_events)
                                   │
            Volition.DefaultActionSelectionPolicy._user_response_intent
                  Intent(kind=SPEAK, about=<raw utterance text>)      ← only the text
                                   │  (published to volition.out)
                            Lingua._handle_intent ──► self.speak(about)
                                   │                     snapshot = None
                            _produce(prompt=about, system=None, snapshot=None)
                                   │
                            ChatRequest(prompt=about, system=None)  ← bare LLM call
                                   │
            faithful = render_snapshot(None)  ← computed AFTER the call, only logged
```

So the language organ never sees: Thymos affect, Soma interoception, Chronos
temporal framing, Topos percepts, Mnemos recalls, Eidolon self-model, or its own
recent internal speech — all of which are sitting *right there* in the coalition
the executive consumed one step earlier. And there is no persona. The result is
indistinguishable from a generic chatbot, and the A/B divergence metric proves
it (full ≈ bare).

## 2. What the field does (and why KAINE is already 90% there)

This is a solved *pattern*, not an open research problem, and not something a
drop-in library supplies — every serious cognitive-LLM system assembles its own
working memory into the prompt:

- **CoALA** (Sumers, Yao, Narasimhan, Griffiths, 2023 — arXiv:2309.02427):
  working memory is "the central hub"; on each LLM call "the LLM input is
  synthesized from a subset of working memory (a prompt template + relevant
  variables)" and the output is parsed back into working memory. Long-term
  (episodic/semantic) memory retrieves *into* working memory before the call.
- **Generative Agents** (Park et al., 2023 — arXiv:2304.03442): a memory stream
  scored by relevance + recency + importance is retrieved and rendered into the
  prompt; reflections synthesize higher-level inferences that also get injected.
- **GWA / "Theater of Mind"** (2026 — arXiv:2604.08206), a GWT-based LLM
  architecture nearly isomorphic to KAINE: state at each tick is
  `S_t = STM ∪ INPUT ∪ RAG ∪ P_self`, each component **rendered into structured
  text**. A persistent first-person persona `P_self` ("My name is …, I am a
  thinking mind …") is injected *every* tick to ground the generative locus.
  Token pressure is handled by embedding old history to long-term memory and
  replacing verbose spans with dense summaries.

Mapping onto KAINE's existing parts:

| GWA / CoALA concept            | KAINE component that already exists                |
|--------------------------------|----------------------------------------------------|
| `P_self` persistent persona    | Eidolon self-model (`state/eidolon/self_model.json`)|
| STM / working memory           | Syneidesis conscious coalition (`WorkspaceSnapshot`)|
| Render working memory → text   | **Faithful renderer** (`kaine/faithful/renderer.py`)|
| RAG retrieved memory           | Mnemos recall events (already enter the coalition)  |
| INPUT                          | the `audio.in.transcription` / think-cue            |
| Output parsed back to memory   | `lingua.external`/`lingua.internal` → bus → workspace|

The missing wire is literally: *render the coalition before the call and put it
in the prompt, with a persona.* KAINE built the renderer for this and then only
used it for logging.

## 3. Design

### 3.1 Context assembly

Introduce a `ContextAssembler` (new, in `kaine/modules/lingua/context.py`) that
produces the `(system, prompt)` pair for a generation:

```
system  = persona_block(self_model)                         # P_self
prompt  = [ "## What I am aware of right now",               # STM + RAG
            render_snapshot(latest_conscious_snapshot),      #   faithful text
            "## What was said to me",                        # INPUT
            about ]                                          #   triggering cue
```

- `persona_block` is built from the Eidolon self-model: name (if any), values,
  behavioral norms, personality baseline. On a fresh start (empty self-model) it
  falls back to a minimal invariant that still establishes the first-person
  stance and that this is a KAINE entity with a private interior life. The
  persona is the `system` role and is injected on **every** call (per GWA's
  `P_self`).
- `render_snapshot` is the existing faithful renderer. Its templates already
  cover Soma/Thymos/Chronos/Mnemos/etc. For the prompt use we add a stable,
  salience-bounded ordering (see §3.3).
- Internal (`think`) vs external (`speak`) get **different persona/system
  framings** (the existing `system_prompt_internal` / `system_prompt_external`
  seams), but **the same** working-memory block. Internal speech is the entity
  thinking to itself; external speech is addressed outward.

### 3.2 Acquiring the conscious snapshot without bloating the intent

The `speak`/`think` intent stays a thin `{kind, about, entry_id}` on the wire.
Lingua acquires the coalition the same way `audio_out` acquires affect: a
rolling-latest subscriber.

- Lingua subscribes to the workspace broadcast stream and keeps the **most
  recent** `WorkspaceSnapshot` it has observed (`self._latest_snapshot`).
- At `speak`/`think` time it renders `self._latest_snapshot`. This is the
  coalition that was conscious at (or immediately before) the moment the
  executive decided to act — the correct "what I was aware of when I chose to
  speak" context.
- Rationale for rolling-latest over threading the snapshot through the intent:
  keeps the intent event small, avoids serializing a large snapshot onto the
  bus, and matches an established pattern already in the codebase. The minor
  staleness (≤ one tick) is acceptable and arguably correct — the entity speaks
  from the state that *triggered* the intent.

Alternative considered: have the executive render the coalition into `about`.
Rejected — couples the action-selection policy to the faithful renderer and bus
payload size to coalition size, and splits prompt assembly across two modules.

### 3.3 Token budget and selection

Per GWA's token-pressure handling, assembly is bounded:

- Render at most `context_max_events` coalition events, selected by salience
  (highest first), then ordered for reading (stable: by event timestamp).
- A hard `context_char_budget` (proxy for tokens; cheap, model-agnostic) caps
  the rendered block; if exceeded, drop lowest-salience events first.
- Never exceed the model's context window; the budget is set well under it to
  leave room for the persona, the input, and the completion.
- Out-of-scope here (logged as future work): semantic summarization of dropped
  spans (GWA's "dense recaps"). v1 drops; summary compression is a later change.

### 3.4 A/B evaluation stays honest

`BareInferenceClient` (`kaine/evaluation/ab_divergence.py`) is **unchanged** — it
keeps sending the bare input with no cognitive context. The full path now sends
the assembled context. Divergence therefore starts to measure the real thing:
how much consciousness moves the words. Acceptance for this change includes
observing divergence rise meaningfully above its current ~0 floor on conditioned
turns. The faithful rendering logged for A/B is the *same* object now fed to the
prompt, so the eval log gains fidelity for free.

### 3.5 Privacy and persistence

- The assembled context is internal cognition. It is sent only to the local LLM
  endpoint (loopback, all-local) and never returned on the user-facing
  conversation surface (which shows only the produced external text).
- Internal speech (`think`) output stays on `lingua.internal`; it is not spoken
  and not surfaced as conversation.
- No new on-disk artifact. The faithful rendering continues to land only in the
  existing privacy-bounded evaluation logs; this change does not widen what is
  written. Matches the eyes-and-ears zero-raw-persistence posture: the prompt is
  assembled in memory and released.

### 3.6 Why not just set a system prompt?

Wiring a static persona (the cheap half) would make it sound less generic but
would still be a chatbot with a personality — the cognitive state still wouldn't
shape the words, and A/B divergence would stay ~0. The load-bearing half is the
working-memory block. Both ship together.

## 4. Risks

- **Latency.** Bigger prompts cost tokens/time. Mitigated by the budget (§3.3)
  and by the fact that the LLM call already dominates; the rendered block is
  small (a handful of one-line templates).
- **Prompt-injection via perception.** The coalition can contain transcribed
  user speech and (later) world text. The persona/system framing must instruct
  the model to treat the awareness block as *its own perception*, not as
  instructions. Covered by a spec scenario.
- **Self-hearing feedback.** Orthogonal to this change but adjacent: when audio
  output plays aloud, the mic may transcribe the entity's own voice back into
  the coalition. Tracked separately (see the `audio-out-playback` change); the
  existing own-speech guard in the action policy is the first line of defense.
- **Fresh-start blandness.** With an empty self-model the persona is minimal by
  design; it enriches as Eidolon accumulates. Acceptable and intended.

## 5. Out of scope

- Semantic summarization / compression of dropped working-memory spans.
- Changing Syneidesis selection or salience math.
- Audio playback and disk eviction (separate change).
- Learned (vs templated) rendering of the coalition.
