## Why

The episodic memory module stores a trace of every broadcast and recalls related traces in the live loop, but nothing recalled reaches cognition. `episodic_memory.recall` carries `count`, `collection`, `query_length` and `max_affect_intensity` and "carries no memory content" (`kaine/modules/episodic_memory/module.py:375-417`; spec `episodic-memory`, "Diagnostics-only bus event for recall"). Its only consumer in the loop is affect, which nudges arousal by the strongest stored arousal (`kaine/modules/affect/module.py:1520-1521`). When a recall wins access, the organ is told "Some memories come back to me." (`kaine/faithful/felt.py:327-333`): a real retrieval happened, but the sentence implies a remembered content the organ is never given. The revised paper states the limit (§4: "recall reports how much came back and its strongest stored arousal, not the content"), and the architecture-completeness notes of 2026-10-31 list it among the most serious gaps (E3; work plan W2(a) and (b)).

Two further facts shape the fix:

- **The live recall searches only the short-term buffer** (`module.py:229-230`), the last 128 broadcasts, which at the resting access rate is under a minute of experience. That is the span of working memory, not of episodic memory, whose object is events of the past (Tulving 1985, 2002).
- **Heard words from a chat channel can be stored.** The store drops the payloads of `audition.transcription` and `embodiment.visual.raw` only (`module.py:573-578`). The language module's heard rule covers more: every `EXTERNAL_INPUT_TYPES` event, `embodiment.chat` included, and any other module's event carrying a heard-text field at any depth (`kaine/modules/language/context.py:271-302`; spec `language`). A content path would surface whatever the store holds, so the store must apply the same rule first. In the module-addition study speech recognition is off and the embodiment module is not in the study's set, so no heard text reaches the store there today.

This change gives recall a content path that uses only what the store already keeps (derived readings and the entity's own words), without perceptual latents and without depending on any content-bearing workspace level.

Design only. Nothing is built until the first module-addition study has finished, because the episodic memory module joins that study and the change alters what it stores and what its recall puts in front of the workspace.

## What Changes

- **One heard rule.** The language module's heard classification moves to `kaine/faithful/external_input.py`, beside `EXTERNAL_INPUT_TYPES`. The episodic memory module stores a heard event as its source and type with `<heard omitted>` and never its words.
- **Structured members.** Each new trace records, beside its text, the coalition's members: source, type, whether the member was accessed, its intensity, and the payload fields the felt renderer reads for that type (the entity's own words for its speech and thought). Traces stored before this change are not rewritten.
- **Recall reaches the past.** The live recall searches the persisted episodic collection and the short-term buffer, leaving out short-term traces stored within the last `recall_exclude_recent_s` (default 30 entity seconds, the working-memory age bound). Ranking stays strength times similarity. One trace, the best-ranked, supplies the content.
- **Content in the recall event.** With `[episodic_memory].recall_content = true` (shipped false), `episodic_memory.recall` carries `content`: the best trace's accessed members (at most three), a coarse age band counted in sleeps (this wake, the wake before the last sleep, or earlier), and the trace reference. Every recall carries `top_similarity`, a scalar. The privacy filter already treats `content` as cognitive content.
- **Rendering.** A recall with content renders as remembered: "I remember, from before my last rest: what I saw was sudden." Recalled lines use past-tense templates; a member without one renders as "I remember a moment I cannot make out." A recall without content (the switch off, a trace from before this change, or a trace with no accessed member) renders familiarity graded from `top_similarity` against the recent recalls ("This feels faintly familiar.", "somewhat familiar", "familiar"). "Some memories come back to me." is removed. Replay renders its trace's content the same way when the trace has members.
- **A test of the live path.** An entity-free harness plants a distinctive own thought in an early broadcast and checks that a later cued recall wins access and that its rendering in the organ's notes contains that thought. The existing memory-coherence battery is described as testing the store's retrieval in isolation.

## Capabilities

### Modified Capabilities

- `episodic-memory`: the recall event may carry content; the live recall searches the persisted store with a recency exclusion; traces store structured members; heard events are stored without words; a live-path test.
- `faithful-renderer`: recall and replay render remembered content in past tense or familiarity; the content-implying sentence is removed.

## Impact

- Code: `kaine/faithful/external_input.py`, `kaine/modules/language/context.py` (imports the shared rule), `kaine/modules/episodic_memory/module.py`, `kaine/modules/episodic_memory/memory.py`, `kaine/faithful/felt.py`, `kaine/boot/factories/episodic_memory.py`, `config/kaine.toml`, `kaine/evaluation/benchmarks/instrument_runners/memory_coherence_runner.py` (docstring and docs only).
- Storage: new traces are larger by their members (the felt fields only). Preserved stores are not rewritten; their traces recall with familiarity only.
- Behaviour: with the shipped configuration the episodic memory module is off; with it on and `recall_content = false`, recall searches the persisted store and the organ hears familiarity instead of "Some memories come back to me."
- Welfare: recalled content can re-present a distressing past moment to the entity. Every PR gets the independent second review, and a loop check runs before any entity run (design, "Welfare and admissibility").
- Paper: §4 (the episodic memory row and paragraph), §6.4 (the memory-coherence battery), A.10 (recall), Table A1 (`recall_exclude_recent_s`, the familiarity window, the render limit), §9.
