## Why

The paper (§63) says Eidolon's self-model fills "through observation of the
system's own patterns over time, including its developing voice and its internal
speech." Today Eidolon only **counts** internal speech (`internal_speech_count`)
and ignores its **content** and ignores **external speech entirely** — so the
"developing voice" is not actually observed (audit finding #5). Drift detection
runs only over module-name source distributions, not over the voice.

## What Changes

- Eidolon observes **both** speech channels: it already reads `lingua.internal`;
  it now also observes `lingua.external`. (Both producer types are now correct
  after `fix-lingua-speech-event-type`.)
- The self-model records the **developing voice** as lightweight, privacy-
  conscious observations: `external_speech_count` (parallel to the existing
  internal count) and a capped rolling `voice_observations` buffer of per-
  utterance features — `{timestamp, channel: internal|external, length,
  word_count}`. **Raw utterance text is NOT duplicated into the persisted
  self-model** (that content already lives in `state/lingua/intent_expression.jsonl`
  for voice alignment; and application-level encryption at rest is still
  deferred). Observing verbosity/frequency over time is enough to capture a
  developing voice for v1; richer content analysis can draw on the intent log
  later.
- `SelfModel` gains `external_speech_count` and `voice_observations`, with JSON
  round-trip and a cap (like `identity_history`).

## Capabilities

### Modified Capabilities

- `eidolon`: the self-model observes the developing voice — both internal and
  external speech, recorded as capped lightweight per-utterance features — not
  just an internal-speech count.

## Impact

- **Code**: `kaine/modules/eidolon/document.py` (`SelfModel` fields + JSON);
  `kaine/modules/eidolon/module.py` (record features in the internal-speech loop;
  add an external-speech loop; cap the buffer). Ctor knobs for cap default on.
- **Privacy**: only derived features persisted, not raw speech text. Noted.
- **Tests**: unit tests (fakes) — internal + external utterances recorded with
  features + counts; buffer cap enforced; JSON round-trip; no raw text stored.
- **Config**: optional `[eidolon].voice_observations_cap` (reported, not
  auto-added).
