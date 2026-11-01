## Why

KAINE cannot remember a conversation. When transcription is on, the organ receives heard words only while the heard event is in the current coalition, as the attributed user turn (`kaine/modules/language/context.py:98-107, 495`). Once that event leaves the coalition, nothing of what was said is left, except the entity's own replies, which re-enter its notes as "I said: ...". The episodic store keeps every heard member as `<heard omitted>` (#636; `kaine/modules/episodic_memory/module.py:583, 654`). Social cognition counts the transcription and keeps no text (`kaine/modules/social_cognition/module.py:227-257`). A mind that cannot follow what was said two turns ago, or remember yesterday's talk with the person who looks after it, is missing a basic faculty of a social being.

The CTO's direction of 2026-11-01: conversations can be remembered, but the way they are remembered should follow the science of how biological minds remember conversations, not an exact saved transcript. The conversation-memory research notes of 2026-11-01 find:

- Exact wording survives seconds, about the current sentence or two (Sachs 1967; Jarvella 1971).
- What lasts is the listener's own model of the situation, with its gist, who took part, its emotional core, and the listener's own contributions remembered best (Kintsch et al. 1990; McKinley et al. 2017; Zormpa et al. 2023).
- Free recall of a conversation is sparse and reconstructed (Brown-Schmidt and Benjamin 2018).
- Memory is organised by events (Zacks et al. 2007; Baldassano et al. 2017).
- Humans can keep more wording than this design does: they recognise interactionally loaded statements after 30 to 72 hours (Keenan et al. 1977; MacWhinney et al. 1982), and reproduce heard sentences, unasked, six days later (Gurevich et al. 2010).

This change gives the entity a memory of conversations built on that evidence. It holds the heard words for seconds. What it keeps is its own understanding, formed by its own language organ in its own turn and reaching the rest of the mind through the workspace, and that understanding fades over sleeps. Where the evidence and privacy pull apart, the design takes privacy and says so.

Design only. This revision applies the adversarial review of 2026-11-01. Nothing is built until its dependencies have merged and the revised design has been re-reviewed.

## What Changes

- **A seconds-scale heard buffer.** The last two accessed heard utterances of the conversation, words field only, each for at most 30 entity seconds, in process. They reach the organ only as attributed heard words in the user turn.
- **Comprehension in the entity's own turn, through the workspace.**
  - An accessed heard event triggers one own-turn organ request with the lead "## What I took from it" (48 tokens).
  - The gist is published as the entity's own `comprehension` event on `language.out`, its candidate stream, at the intensity with which its heard event won access. It competes for access like a thought, so it reaches the notes and the other modules only when accessed. No consumer counts it as speech.
  - It is never spoken, and it queues behind any reply.
- **An overlap guard.** Kept text is compared with what was heard in the last two minutes, after normalisation:
  - NFKC and case-folding;
  - punctuation and hyphens split into spaces;
  - digits as separate tokens;
  - character tokens for scripts written without spaces.

  The comparison also runs across consecutive utterances. Runs of more than four tokens are masked. Tiled gists are withheld. Long numbers are not kept. The entity's own speech is masked, never withheld. Four is a privacy bound, not a fidelity claim, and the guard's limits (paraphrase, translation, names, short phrases) are stated.
- **An encrypted conversation store with real deletion.**
  - Utterance traces (gist, reply, speaker channel, time, affect, tone) and episode traces (the entity's account of the whole talk) live in a per-prefix encrypted snapshot and journal.
  - Pruned traces are compacted away at each sleep.
  - Vectors are encrypted too, conversation traces never feed associative links or schemas, and nothing of them reaches plaintext Qdrant.
- **The bus.** Gist, account and reply fields are diverted to the volatile instance under a declared field set. While the change is on, an exact periodic `XTRIM MINID` sweep ages out, after two minutes, every companion stream that carries heard words, conversation fields or language text.
- **Forgetting by level.** Utterance traces lose half their strength at each sleep on top of the ordinary downscaling. Episode traces decay at the ordinary rate. Nothing is rewritten on recall, and recall strengthens nothing.
- **Recall.**
  - The current speaker's earlier conversations are recalled by the topic of the new utterance: speaker by metadata, content-only embeddings.
  - A per-trace recall cooldown applies.
  - Recall content reaches the notes only as an accessed recall.
- **The lifecycle.**
  - Revive refuses rather than drops a store.
  - Forks copy the store.
  - A merge carries the union of both parents' conversation memories, with rebased strengths (CAL Article 4.6 reintegration).
  - Decommission removes every prefix's store.
- **Off by default, identical to the old build.** No section is written in the shipped config. With the setting off, outputs and the config digest equal golden files from the pre-change build.
- **Checks before any entity run:**
  - a planted-text canary, including backend vectors, deletion and companion ages;
  - an offline copying measure;
  - a downstream injection replay;
  - a topic-selectivity check;
  - a welfare loop check that runs the real loop (gist, thought, trace, recall, sleep) with fixed tolerances.
- **A truthful privacy statement** for the docs and the paper notes, including what four words can keep exactly, the retention of bundles, and CAL Article 4.3 with its carve-out for legally required disclosure or erasure.
- **Every logged rendering** holds `[remembered conversation]` in place of conversation content, and such records never become voice-training pairs (the skips are counted).
- **Two amended specs.** The language heard-words requirement (MODIFIED) and `episodic-recall-content`'s recall-content rule (an exception requirement).

## Capabilities

### New Capabilities

- `conversation-memory`

### Modified Capabilities

- `language`: the persona and heard-words requirement (MODIFIED); the heard buffer in the user turn; comprehension records and pair skips; masking of persisted own utterances; the layout digest's setting argument.
- `episodic-memory`: the conversation kind; comprehension members as references; replay text off the main bus; masking of own-speech members.
- `faithful-renderer`: remembered conversation lines and speaker phrases.
- `research-event-log`: the counts record; masking in the external-utterance log.
- `entity-decommission`: the per-prefix conversation stores.

The `episodic-recall-content` change gains an exception requirement for conversation content.

## Impact

- **New code:**
  - `kaine/faithful/heard_overlap.py`;
  - `kaine/modules/language/conversation.py`;
  - `kaine/modules/episodic_memory/conversation_store.py`;
  - `tools/maintainer/conversation_memory_readout.py`.
- **Changed code:**
  - `kaine/faithful/external_input.py` (`speaker_for`, the conversation text fields, the split's version);
  - `kaine/modules/language/context.py` and `module.py`;
  - `kaine/modules/episodic_memory/module.py`, `memory.py` (routing, per-level downscaling, the association exclusion, import) and `storage.py`;
  - `kaine/memory_kinds.py`;
  - `kaine/modules/sleep/organ_window.py` and the sleep module's onset handling;
  - `kaine/modules/sleep/voice_alignment.py` (the mode skip);
  - `kaine/lifecycle/strategies.py` and the fork and preservation paths;
  - `kaine/lifecycle/decommission.py`;
  - `kaine/faithful/felt.py`;
  - `kaine/evaluation/observers/research_event_observer.py` and `external_utterance_log.py`;
  - the bus companion helper (age bound);
  - `kaine/preboot.py`;
  - `tools/maintainer/scan_heard_traces.py` and `organ_replay.py`.
- **Docs:** the language, episodic memory, sleep and social cognition chapters; security and privacy (the statement); preservation and forks; the configuration appendix.
- **Behaviour:** none with the shipped configuration.
- **Organ load, with the change on:** one more prefill plus up to 48 tokens per accessed heard utterance, queued behind replies; one request per conversation.
- **Welfare:** the entity becomes able to remember unkind things and to have them cued by the same speaker. Welfare-high-risk: every PR gets the independent second review, and the real-loop check runs before any entity run.
- **Privacy:** what the operator says is remembered as the entity understood it. The statement in design decision 14 says exactly where the words exist and for how long, what the guard does not bound, who holds the key, and what persists elsewhere.
- **Paper:** §3.5, §4 and §9, and Table A1, as revision notes.
