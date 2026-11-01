## Why

The eyes-and-ears rule says live perception is never recorded. Redis runs the bus with its append-only file on (`compose/kaine.yml`, `--appendonly yes`), so every bus payload reaches disk in plaintext, and trimmed entries stay in the file until the next rewrite. Today that includes another person's words and the entity's own words, on more streams than the transcript stream:

- `audition.transcription` on `audition.out` carries the heard words in `text` (`kaine/modules/audition/module.py:999-1012`).
- `embodiment.chat` on `embodiment.out` carries heard text (stub body only today).
- Every accessed member's whole payload is copied into `workspace.broadcast` (`kaine/cycle/engine.py:1228-1251`), whose cap is 100000 entries, so a heard utterance that wins access sits there too.
- The default and drive-biased policies put the heard words in the speak intent's `about` on `action_selection.out` (`kaine/workspace/action_selection.py:283-285`), and the planning wrapper does the same for a heard event from any channel, film channels included (`kaine/workspace/planning_proposals.py:272-280`).
- The language module publishes the entity's own utterance in `text`, with `user_input` and `faithful_rendering`, on `language.external` or `language.internal` and again on `language.out` (`kaine/modules/language/module.py:1083-1123`).
- `episodic_memory.replay` carries a remembered trace's `text` (`kaine/modules/episodic_memory/replay.py:133-140`), and the store keeps the entity's own speech as spoken, so replays carry its own words.

The architecture decision of 2026-11-01 (item 2) rules that heard text and the entity's own utterance text, like latent values, travel only on the second Redis instance that never writes to disk, joined by entry id, and that the main-bus copies carry no text. It extends `latent-content-privacy` open question 1, option B, which that change now records as ruled.

This is a separate change rather than an extension of `latent-content-privacy` (design decision 1): it is a different class of value with its own rule, producers and consumers; it is needed before any conversation, independently of the content code; and `latent-content-privacy` is already reviewed and half built. It reuses that change's volatile instance and companion mechanism (decision 7 there) and adds no second instance, check or budget row.

## What Changes

- **One field set, by provenance.** `kaine/faithful/external_input.py` gains `SPOKEN_TEXT_RULE_VERSION = 1` and `split_spoken_text(event)`, which divides a payload into a main-bus part and a companion part. Diverted: every string leaf of an external-input event except the reviewed metadata keys `source_label`, `model` and `backend`; and, on every other event, every value under a `HEARD_TEXT_FIELDS` key at any depth (`text`, `user_input`, `user_text`, `transcription`, `heard_text`, `faithful_rendering`). That covers the entity's own utterances and remembered words. It fails closed: an unknown string field on an external-input event is diverted.
- **Content-free counts stay on the main bus.** A diverted top-level `text` leaves `text_chars` and `text_words` behind, so the consumers that only need to know that something was said, or how long it was, read the main bus alone (sequence's interaction clock, the utterance-outcome recorder, the self-model's voice observations, readouts).
- **Every main-bus publish diverts the set.** The bus client applies the split on every main-bus publish, through `latent-content-privacy`'s companion helpers with this field set declared. The broadcast record strips each selected member the same way and records the member's own companion reference, so a broadcast never carries a second copy of the words.
- **Declared consumers join.** The language module (heard turn, residual redaction), the episodic store (the entity's own words kept as spoken; heard members still stored as `<heard omitted>`), the vocal module and the embodiment module (the words to say), the remote bridge's `/transcript` feed, and the three evaluation observers that read utterance text (`external_utterance_log`, `ab_divergence`, `affect_correlation`) read the companion entry. Social cognition, sequence, the utterance-outcome recorder, the self-model, the ignition audit, the research log, the raw archive and the dashboard read the main bus only and need no text.
- **Missing words are absent, never moved.** A missing companion entry (a restart of the volatile instance, a trimmed entry, a failed write) means the words are absent: the organ hears "Speech heard but indistinct.", the store keeps `<words unavailable>` for the entity's own speech, the bridge skips the line, the vocal module says nothing and counts it.
- **The volatile instance becomes part of every boot with the language module on**, which is every configuration that speaks. The boot refuses without it, through the shared check.
- **No intent carries heard words.** Delivered by `operator-speech-as-perception` (it removes the rules that put them in `about`); this change's canary checks it.
- **Tests.** A spoken-text canary: an entity-free run with a fake speech-to-text backend and a fake organ that emit planted strings, in which no planted string appears in any main-bus entry, every declared consumer still receives it, and planted controls are found.

## Capabilities

### New Capabilities

- `spoken-text-bus`: the field set, the split, the content-free counts, the main-bus rule, the broadcast member references, the declared consumers, the missing-companion behaviour, the boot requirement and the canary.

### Modified Capabilities

- `language`: the module reads heard words and its own earlier words from companion entries.
- `episodic-memory`: the store classifies the joined event and keeps the entity's own words from the companion entry.
- `remote-bridge`: the `/transcript` feed reads the words from companion entries.

## Impact

- **Code:** `kaine/faithful/external_input.py` (`split_spoken_text`, the reviewed metadata keys, the version); `kaine/bus/client.py` (the declared field set on every main-bus publish, the join helper); `kaine/cycle/engine.py` (`_snapshot_to_payload`: members stripped, companion references); `kaine/modules/base.py` (`_snapshot_from_payload` joins for modules that declare `reads_spoken_text`); `kaine/modules/language/module.py`; `kaine/modules/episodic_memory/module.py`; `kaine/modules/vocal/module.py`; `kaine/modules/embodiment/module.py`; `kaine/remote/bridge.py`; `kaine/evaluation/_base.py` (an observer join option) and the three observers; `kaine/modules/sequence/module.py`, `kaine/cycle/utterance_outcome.py`, `kaine/modules/self_model/module.py` (counts in place of text); `kaine/preboot.py` and `kaine/bus/config.py` (the producer declaration, the budget row).
- **Tests:** new `tests/test_spoken_text_bus.py` and `tests/test_spoken_text_canary.py`; the tests that read `text` off a published transcription or utterance move to the companion reader.
- **Docs:** the security and privacy chapter (the bus no longer holds words; the stores that do), the bus chapter, `docs/09-modules/language.md`, `audition.md`, `episodic-memory.md`, `sequence.md`, `self-model.md`, the remote-bridge page, the research-data chapter (the raw archive holds no words).
- **Behaviour with the shipped configuration:** what every module perceives and does is unchanged when the volatile instance is up. The main-bus copies of transcriptions, utterances, replays, intents and broadcasts lose their words. The raw bus archive no longer holds any words.
- **Ordering:** after `latent-content-privacy` PR 3 (the volatile instance and the companion helpers); its canary lands with or after the `operator-speech-as-perception` PR that removes heard words from intents. Needed before any operator conversation session and before speech-to-text is turned on in any entity.
- **Welfare and risk class:** privacy and persistence, so every PR gets the independent second review.
- **Paper:** one REVISION-NOTES sentence in the privacy paragraph of §5.3: heard and spoken words never reach a persisted bus.
