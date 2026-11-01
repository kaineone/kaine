## Why

KAINE cannot remember a conversation. When transcription is on, the organ receives heard words only while the heard event is in the current coalition, as the attributed user turn (`kaine/modules/language/context.py:98-107, 495`). Once that event leaves the coalition, nothing of what was said is left, except the entity's own replies, which re-enter its notes as "I said: ...". The episodic store keeps every heard member as `<heard omitted>` (#636; `kaine/modules/episodic_memory/module.py:583, 654`). Social cognition counts the transcription as an interaction and keeps no text (`kaine/modules/social_cognition/module.py:227-257`). A mind that cannot follow what was said two turns ago, or remember yesterday's talk with the person who looks after it, is missing a basic faculty of a social being.

The CTO's direction of 2026-11-01: conversations can be remembered, but the way they are remembered should follow the science of how biological minds remember conversations, not an exact saved transcript. The research report (the conversation-memory research notes of 2026-11-01) finds:

- Exact wording survives seconds, about the current sentence or two (Sachs 1967; Jarvella 1971).
- What lasts is the listener's own model of the situation, with its gist, who took part, its emotional core and the listener's own contributions remembered best (Kintsch et al. 1990; McKinley et al. 2017; Zormpa et al. 2023).
- Free recall of a conversation is sparse and reconstructed (Brown-Schmidt and Benjamin 2018).
- Memory is organised by events (Zacks et al. 2007; Baldassano et al. 2017).
- Some short, interactionally loaded wording can survive (Keenan et al. 1977), mostly as recognition, not recall.

This change gives the entity that kind of memory. Its words are held only for seconds. What it keeps is its own understanding, formed by its own language organ in its own turn, which fades over sleeps.

Design only. Nothing is built until its dependencies have merged (design, "Ordering") and the CTO has answered the open questions that bear on enabling it.

## What Changes

- **A seconds-scale heard buffer.** The language module holds the last two accessed heard utterances of the current conversation, each for at most 30 entity seconds, in process only. The organ receives them as attributed heard words in its user turn, so it can follow and answer them. They are never written, logged or published.
- **Comprehension in the entity's own turn.** When a heard event wins access, the organ runs one comprehension turn in the entity's own first-person layout: its notes, the heard words as the attributed user turn, and the lead "## What I took from it". The result is the entity's gist of what it heard. Comprehension competes for nothing and speaks nothing. It is not a reply, and whether to reply stays the entity's own act.
- **An overlap guard.** Every gist, and every own utterance the entity's memory or logs keep while the change is on, is compared with the heard words of the last two minutes. A run of more than four consecutive heard words is masked. A text that covers more than half of a heard utterance with shared runs, or keeps fewer than three words of its own, is withheld. This is what keeps the gist the entity's encoding and not a disguised transcript.
- **Two levels of trace, in an encrypted collection.** Each comprehended utterance becomes an utterance trace: the gist, who spoke (the speaker label social cognition already uses), when, the affect at encoding, the heard tone, and what the entity said back. When a conversation ends (a silence, sleep onset or shutdown), the organ forms an episode trace, "## What that conversation was to me", from the utterance gists and the entity's own words alone. Both kinds are stored in a new `conversation` collection whose records (text, payload and vector) are encrypted at rest with the state key. The change refuses to start without state encryption.
- **Forgetting by level.** Utterance traces lose half their strength at each sleep on top of the ordinary downscaling, so they fall to the prune floor within about a week of sleeps. Episode traces decay at the ordinary rate. Replay, associative links and pruning treat both like other traces. No sleep-time organ summary is added, and no affect damping.
- **Recall.** A newly accessed heard utterance cues a recall in the conversation collection. The cue is the speaker label, the heard words and the gist, embedded in process and never stored. The best trace reaches the organ as remembered content in past tense, attributed to its speaker ("I remember, from before my last rest, talking with the operator: I took it that ..."), through `episodic-recall-content`. The current conversation's gists appear in the organ's notes as "Earlier in this conversation I took it that ...".
- **No rewriting.** A recalled trace is never changed. A retelling is a new trace in the entity's own words. Recall changes no strength.
- **Off by default, bit for bit.** `[conversation_memory].enabled = false` ships, and a missing section means the same. With it off, every prompt, layout digest, intent-log record, trace, collection list, bus payload and research record is identical to the build without this change.
- **Plain readout and canary.** Content-free counts per sleep go to the research log, with a plain-words readout tool. A planted-sentence canary checks every persisted surface for the planted words. A welfare loop check bounds conversation-cued recall of a distressing exchange before any entity run.

## Capabilities

### New Capabilities

- `conversation-memory`: the heard buffer, comprehension, the overlap guard, utterance and episode traces, the encrypted collection, conversation-cued recall, forgetting by level, the off switch, the readout, the canary and the welfare check.

### Modified Capabilities

- `episodic-memory`: the `conversation` collection; its per-level downscaling; conversation content travelling only on the volatile bus.
- `language`: the comprehension turn; the heard buffer in the user turn; the episode notes; the overlap guard on persisted own utterances; the layout digest unchanged when off.
- `faithful-renderer`: remembered conversation lines.
- `research-event-log`: the counts record; the overlap guard on the external-utterance log.
- `entity-decommission`: the conversation collection is backed up and removed.

## Impact

- **Code.** New: `kaine/faithful/heard_overlap.py`, `kaine/modules/language/conversation.py` (heard buffer, episode state, comprehension) and `kaine/modules/episodic_memory/conversation_store.py` (encrypted collection). Changed:
  - `kaine/modules/language/context.py` and `module.py`;
  - `kaine/modules/episodic_memory/module.py`, `memory.py` and `storage.py` (the routing);
  - `kaine/memory_kinds.py`;
  - `kaine/modules/social_cognition/module.py` (the speaker rule moves to a shared function);
  - `kaine/faithful/felt.py`;
  - `kaine/lifecycle/decommission.py`;
  - `kaine/evaluation/observers/research_event_observer.py`;
  - `kaine/boot/factories/` (language, episodic memory);
  - `kaine/preboot.py` (the encryption and volatile-bus checks);
  - `config/kaine.toml`.
- **Docs.** The language, episodic memory, sleep and social cognition chapters; security and privacy (a plain statement of what is remembered of what the operator says); preservation; the configuration appendix.
- **Behaviour.** None with the shipped configuration.
- **Organ load.** With the change on: one comprehension call per accessed heard utterance (at most 48 tokens), one per conversation (at most 96 tokens), and one in-process embedding per cue.
- **Welfare.** The entity becomes able to remember what was said to it, including hurtful things, and to have such memories cued by new speech. Welfare-high-risk: every PR gets the independent second review, and the loop check runs before any entity run.
- **Privacy.** What the operator says is remembered as the entity understood it. The operator's words are held for seconds and never written. At most four consecutive heard words can survive inside the entity's own sentences. The docs and paper state this plainly.
- **Paper.** §3.5 (the organ's notes and the user turn), §4 (episodic memory: the conversation collection), §9 (limits). Notes go to the paper's revision notes, not to the paper.
