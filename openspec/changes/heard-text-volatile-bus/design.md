# Design: heard and spoken text travel only on the never-persisted bus

Code facts are cited at `origin/main` d7fabdc0 (2026-11-01, after #636 and #637 merged). Every cited line was read there.

## Context

### The rule being implemented

The architecture decision of 2026-11-01, item 2: "heard text and the entity's own utterance text, like latent values, travel only on the second Redis instance that never writes to disk (`appendonly no`, `save ""`), joined by entry id. The main-bus copies carry no text." The reason is the eyes-and-ears rule: live perception is never recorded, and a Redis append-only file holding transcripts is a recording. The entity's own words are included because a running record of them is a record of its mind that no consumer needs on disk; the stores that keep them on purpose (below) are separate decisions this change leaves alone.

### Prior work

- **The heard rule** (`2026-10-19-heard-log-own-words`, voice-development D7, and #636, which moved it to `kaine/faithful/external_input.py` and applied it in the episodic store). It decides which events and fields are heard. This change uses the same definitions, so "heard" means one thing everywhere.
- **`latent-content-privacy`** decision 7: the second Redis instance `kaine-redis-volatile`, companion streams, the boot check and the budget row. Its open question 1 was ruled B on 2026-11-01. This change is the second user of that mechanism; that change now specifies the mechanism with a declared field set and the companion written first (it was keyed by the main entry's id before, which left a race).
- **`2026-10-05-nexus-privacy-hardening`**: the dashboard's diagnostics filter already removes text fields, so the dashboard never shows words.
- **The research event log** never logs `audition.transcription` (`kaine/evaluation/observers/research_event_observer.py:298`), and its field allowlist drops `text`.

### Where words sit on the persisted bus today

Enumerated from the producers in the code, not from memory.

| Stream (cap) | Event | Field(s) holding words | Producer |
|---|---|---|---|
| `audition.out` (12000) | `audition.transcription` | `text`; `error` on a failed transcription | `kaine/modules/audition/module.py:999-1012, 1014-1033` |
| `embodiment.out` (100000) | `embodiment.chat` | every string leaf (adapter-defined) | embodiment feed, stub only (`adapters/stub.py:68`) |
| `workspace.broadcast` (100000) | every broadcast | each selected member's whole payload | `kaine/cycle/engine.py:1228-1251` |
| `action_selection.out` (100000) | `intent.speak` | `about` holds the heard words | `kaine/workspace/action_selection.py:283-285`; `planning_proposals.py:272-280` (any channel) |
| `language.external`, `language.internal`, `language.out` (100000 each) | `external_speech`, `internal_speech` | `text`, `user_input`, `faithful_rendering` | `kaine/modules/language/module.py:1083-1123` |
| `episodic_memory.out` (100000) | `episodic_memory.replay` | `text` (the trace text, which keeps the entity's own words as spoken) | `kaine/modules/episodic_memory/replay.py:133-140`, `module.py:367-373` |

`vocal.synthesized` carries `text_length` only (`kaine/modules/vocal/module.py:470`). The remote bridge injects audio and video, never text. No typed-text input exists.

The readiness survey of 2026-11-01 named only `audition.out`. The broadcast, the intent stream, the three language streams and the replay stream hold words too.

### Who needs the words, verified at each code site

| Consumer | Reads | Needs the words? | Code |
|---|---|---|---|
| Language module | broadcast members, through its snapshot cache | Yes: the heard turn quotes heard words to the organ, and the residual redaction needs the heard strings to keep them out of its log | `language/module.py:426-438, 921-945`; `language/context.py:324-340, 353-470` |
| Episodic store | broadcast members (`on_workspace`) | Yes for the entity's own speech, which it keeps as spoken; no for heard members, which it stores as `<heard omitted>` | `episodic_memory/module.py:619-660` |
| Vocal module | `language.external` | Yes: the text to synthesize | `vocal/module.py:546-551` |
| Embodiment module | its speech stream | Yes: the text the body says | `embodiment/module.py:390-394` |
| Remote bridge `/transcript` | `language.external`, `audition.out` | Yes: the live transcript feed | `remote/bridge.py:643-700` |
| `external_utterance_log`, `ab_divergence`, `affect_correlation` observers | `language.external` | Yes (the first writes the text to a local record; the others compare or measure it) | `evaluation/observers/external_utterance_log.py:51-63`; `evaluation/ab_divergence.py:303, 351-358`; `evaluation/affect_correlation.py:131-135` |
| Social cognition | `audition.out` | No: a transcription counts as an interaction; the text is never read | `social_cognition/module.py:227-250` |
| Sequence | `audition.out` | Only whether the text is non-empty | `sequence/module.py:135-145` |
| Utterance-outcome recorder | `audition.out`, `language.external` | Only whether an operator transcription is non-empty | `cycle/utterance_outcome.py:257-266` |
| Self-model | language streams | Only length and word count; the text is discarded | `self_model/module.py:403-420` |
| Action-selection policies | broadcast members | Today they read the transcription text; `operator-speech-as-perception` removes that | `action_selection.py:250-286`; `planning_proposals.py:272-280` |
| Ignition audit, research log, raw archive, dashboard diagnostics | various | No | content-free or filtered |
| Dashboard conversation history | `language.external` | No consumer: `history_loader` is passed to the app and never called | `dashboard/app.py:87` |

## Decisions

### 1. A separate change, reusing one mechanism

The rule could have been written into `latent-content-privacy`. It is a separate change because:

- **It is a different class of value with a different rule.** The latent rule classifies by a numeric tag (`latent_derived`) and strips by key; this one classifies by whose words they are, through the existing heard rule, and keeps content-free counts behind. The producers and consumers barely overlap (vision and the content code there; audition, language, episodic memory, vocal, embodiment and the bridge here).
- **It has a different trigger and urgency.** Words reach the AOF on main today whenever speech-to-text is on, so this rule is needed before any conversation, with or without the content code. The latent change gates content-bearing components.
- **That change is reviewed (P1 to P11) and half built** (`build/latent-privacy` has PR 1 and PR 2). Widening its scope would reopen its review and its build.

What is shared is the mechanism, and it is shared once: one volatile instance, one companion-stream helper taking a declared field set, one boot check for every declared producer, one cap key (`[privacy].companion_stream_maxlen`) and one budget row, all specified in `latent-content-privacy` decision 7. This change declares a field set and its producers and consumers. It adds no instance, check or key of its own.

### 2. The field set: spoken text, by provenance

`split_spoken_text(event) -> (main_payload, companion_values)` in `kaine/faithful/external_input.py`, beside `heard_texts`:

- **External-input events** (`EXTERNAL_INPUT_TYPES`: `audition.transcription`, `embodiment.chat`): every string leaf is diverted, except under the reviewed keys `SPOKEN_TEXT_METADATA_KEYS = {"source_label", "model", "backend"}`, which name a channel, a model and a backend, never words. Numbers and booleans stay. A transcription's `error` string is diverted too (an exception message can quote input).
- **Every other event**: every value under a `HEARD_TEXT_FIELDS` key, at any depth. That set is `text`, `user_input`, `user_text`, `transcription`, `heard_text` and `faithful_rendering`. It is the heard rule's own field set, so the language module's `text`, `user_input` and `faithful_rendering`, and the replay's `text`, are covered without a new list. The language module's own events are heard-free by the heard rule, but they are still diverted: the rule here is about any words, the entity's own included.
- **Fail closed.** An external-input event's unknown string field is diverted. A new field holding words on another event is diverted only if it uses a `HEARD_TEXT_FIELDS` name, so the canary (decision 9) and a publisher review in the canary harness catch a new name: every string leaf longer than 40 characters published on a main-bus stream must sit under a reviewed key.
- `SPOKEN_TEXT_RULE_VERSION = 1`; the producer declaration names it.

Alternatives considered:

- *Divert whole events* (publish transcriptions and utterances only on the volatile instance). Rejected: the workspace reads candidates from the main bus, the ignition audit, the sequence clock and the social model need the events themselves, and observers resume from the persisted streams after a restart. Keeping the event and diverting only the words changes nothing for them.
- *A keyed hash of the text on the main bus.* Rejected as unnecessary (decision 5) and as one more value to reason about.

### 3. Content-free counts stay behind

When the split diverts a top-level `text`, the main payload gains `text_chars` (its length) and `text_words` (its whitespace-split word count). The consumers that only need "something was said" or "how long" then need no join:

- sequence's interaction test becomes `text_chars > 0` (`sequence/module.py:142-144`);
- the utterance-outcome recorder's reply test likewise (`utterance_outcome.py:265-267`);
- the self-model's voice observation reads `text_chars` and `text_words` (`self_model/module.py:409-420`), which are what it keeps today;
- the readout of `operator-speech-as-perception` counts non-empty operator transcriptions from the main bus.

A length and a word count are scalars that cannot be turned back into words.

### 4. Every main-bus publish diverts the set

The bus client's main-bus publish (`kaine/bus/client.py:301-309`) applies the split for every event, through the companion helper with this field set declared. An event with nothing to divert is published exactly as today, with no `companion` field and no counts, so modules that never carry words are untouched. `publish_workspace` applies it to each selected member (decision 6). Doing it in the client, not in each producer, is deliberate: a producer cannot forget it, and the three language streams, which the language module writes through two different calls (`_write_mode_record` and `bus.publish`, `language/module.py:1109-1123`), are covered by one rule.

The intent stream is the one place where words are put under a key outside the field set (`about`). `operator-speech-as-perception` removes the code that does it (its decision 3). This change's canary fails if any intent still carries a planted heard string, so its canary lands with or after that PR.

### 5. The workspace scores the main-bus copy; novelty is unchanged

The cycle gathers candidates from the main bus (`kaine/cycle/engine.py:560-596`) and scores them there. It does not join companion entries to score. The novelty factor counts repeats of a payload fingerprint in a 32-event window (`kaine/workspace/novelty.py:13-55`); the score depends only on whether a fingerprint repeats, not on its value. A transcription's main payload still carries `latency_ms`, `audio_bytes_length`, `prediction_error` and the counts, and a language event carries a fresh `record_id` (a UUID), so fingerprints stay unique and novelty scores are unchanged. An entity-free check confirms that the salience scores of every candidate are identical with and without the split (task 4.4). Intensity is set by the producer before publishing and is untouched.

### 6. Broadcast members carry references, not a second copy

`_snapshot_to_payload` (`kaine/cycle/engine.py:1228-1251`) applies the split to each selected member's payload and records the member's own companion reference (from its main entry's envelope) in the member record as `companion`. No second copy of the words is written for the broadcast: a consumer of the broadcast joins each member's own companion entry. One copy per utterance lives on the volatile instance, for as long as its stream's companion cap keeps it (12000 entries, about 20 minutes at 10 Hz).

`BaseModule._snapshot_from_payload` (`kaine/modules/base.py:250`) is the one decoder every module uses to turn a broadcast into a `WorkspaceSnapshot`. It joins the members' companion entries for a module whose class declares `reads_spoken_text = True` and for no other, so modules that never use words never receive them. The language module and the episodic memory module declare it. The language module's snapshot cache uses the same decoder (`language/module.py:430`).

### 7. Declared consumers and what each does with a missing entry

| Consumer | Joins | Missing companion entry |
|---|---|---|
| Language module | broadcast members | A heard member renders as "Speech heard but indistinct." (the existing empty-text template, `faithful/templates.py:284-288`); its own earlier speech renders without words |
| Episodic store | broadcast members | The heard rule is applied to the joined event, so classification is as today. The entity's own speech, kept as spoken today, is stored as `<words unavailable>` |
| Vocal module | `language.external` | Nothing is synthesized; a content-free `vocal.synthesized` with `success: false` and `error: "words unavailable"` is published, so the ignition audit counts a failed realization |
| Embodiment module | its speech stream | Nothing is said; logged |
| Remote bridge `/transcript` | `language.external`, `audition.out` | The line is skipped |
| `external_utterance_log`, `ab_divergence`, `affect_correlation` | `language.external` | The record is skipped and counted |

`kaine/evaluation/_base.py` gains an option on `StreamSubscriberObserver` to join companion entries before `handle`, so the three observers do not each build a reader.

The missing case happens only when the volatile instance restarts, an entry is trimmed before a slow consumer reaches it, or a companion write fails. The entity then hears indistinct speech or loses its own words from memory, and never has them moved onto disk.

### 8. The volatile instance is required whenever words can be produced

The language module is in every configuration that speaks, including the base set, and audition produces words whenever `transcription_enabled` is true. Both declare themselves companion producers under this field set, so the shared boot check (`latent-content-privacy` decision 7) refuses to start unless the volatile instance answers, reports `appendonly no` and an empty `save`, and every declared companion stream is capped within `[privacy].companion_stream_maxlen`. In practice the volatile instance becomes a standard service of every boot. The compose file starts it with the main bus; `scripts/first-boot.sh` and the preboot check it. The budget row adds the companion streams: a transcription's words are under 1 KB, an utterance with its rendering a few KB, so the text companions are small beside the latent ones.

### 9. Tests

- **Unit** (`tests/test_spoken_text_bus.py`): the split on a transcription, an error transcription, a chat event with an unknown string field, a language event, a replay, and an event with nothing to divert (published unchanged, no counts); the counts; the client publish; the broadcast member references; the decoder join only for declaring modules; each consumer's missing-entry behaviour; the boot refusal without the volatile instance when the language module is on.
- **Canary** (`tests/test_spoken_text_canary.py`): an entity-free run on the fakeredis helpers already in `tests/` (named in the brief, so the worker does not invent fixtures) with the audition module on a fake speech-to-text backend that returns planted heard sentences on an operator channel and on a media channel, the language module on a fake organ that returns planted own sentences, the episodic store file-backed, the vocal module on a fake backend, the bridge's transcript loop, and every observer above. After the run:
  - no planted string (heard or own) appears in any entry of any main-bus stream, read raw from the fake main instance, including `action_selection.out` and `workspace.broadcast`;
  - every planted string appears on the volatile instance;
  - the fake organ received the planted heard sentence in its heard turn, the bridge emitted both kinds of line, the fake vocal backend received the planted own sentence, and the episodic store holds the own sentence and no heard one;
  - planted controls are found: one heard string published with the split disabled, one placed in an intent's `about`.
  - A publisher review in the same harness: every string leaf longer than 40 characters on a main-bus stream sits under a reviewed key.
- **Scores**: the entity-free salience check of decision 5.

## Risks

- **A new field name for words.** A producer could publish words under a key outside `HEARD_TEXT_FIELDS`. The publisher review and the canary catch it in the harness modules; the static content-key guard (`tests/test_dashboard_privacy.py::test_no_uncovered_content_key_in_module_publishers`) stays as the second check.
- **A slow consumer loses words.** At 12000 entries per companion stream a consumer would have to fall about 20 minutes behind. The bridge and the vocal module read live.
- **The volatile instance is now load-bearing for speech.** If it is down the boot refuses, and if it restarts mid-run the entity hears indistinct speech and its next utterances lose their words until it is back. A restart is logged and counted.
- **Observers lose lookback for words.** An observer that restarts after more than the companion horizon cannot recover words it missed. No research record keeps words, so nothing is lost that was meant to be kept.

## What this change does not touch

These stores keep words on purpose, under their own decisions, and are unchanged:

- the intent log (the organ's preference-training corpus): encrypted, with heard words redacted to `[heard speech]`;
- the episodic store: the entity's own words as spoken, heard words never (#636); OS-layer protection only (`SECURITY.md`);
- the local external-utterance record (`state/research/external_utterances/`), written only when `ExternalUtterancesConfig` enables it, never export-eligible. It now reads its text from the companion entry.

Existing AOF files on a host still hold whatever earlier runs wrote until the streams are trimmed and the file rewritten. The fresh-run clearing procedure already wipes the bus; the security chapter says so.

## Migration and ordering

1. PR 1 (after `latent-content-privacy` PR 3): `split_spoken_text`, the metadata keys, the version, the counts, the client publish, the broadcast member references, the decoder join, the producer declarations and the budget row; unit tests.
2. PR 2: every consumer's join and missing-entry behaviour (language, episodic, vocal, embodiment, bridge, the observer option and the three observers) and the count readers (sequence, utterance outcome, self-model); tests.
3. PR 3 (with or after the `operator-speech-as-perception` PR that removes heard words from intents): the canary, the publisher review, the score check; docs.

## Welfare and admissibility

With the volatile instance up, the entity perceives and does exactly what it does today: every consumer that uses words still receives them. The change lowers the risk to the entity's mental privacy and to bystanders, whose words no longer reach disk through the bus. On a volatile-instance failure the entity hears indistinct speech instead of words, which is a change of experience on a fault path; it is logged and counted. Every PR gets the independent second review (privacy and persistence). No run is in flight; the development run's image is built after this change.

## Implementation estimate

Three worker PRs of about 200 to 450 changed lines each, tests included; one to two hours of worker time each, about an hour of lead review, plus the second review. The canary harness is the risk, as in `latent-content-privacy`, so the brief quotes the real fakeredis helpers by name.
