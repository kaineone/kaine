## 1. SelfModel fields

- [x] 1.1 Add `external_speech_count: int = 0` and `voice_observations:
      list[dict] = []` to `SelfModel` (`kaine/modules/eidolon/document.py`);
      update `from_json` to read them with safe defaults (empty/zero).

## 2. Observation loops

- [x] 2.1 In `kaine/modules/eidolon/module.py`, extend the internal-speech loop
      to record a feature dict `{timestamp, channel:"internal", length,
      word_count}` per utterance (read text from payload, compute, discard) and
      bump `internal_speech_count` as before.
- [x] 2.2 Add a symmetric external-speech loop reading `lingua.external`,
      recording `channel:"external"` features and bumping
      `external_speech_count`.
- [x] 2.3 Cap `voice_observations` to `voice_observations_cap` (ctor kwarg,
      default 256); report the `[eidolon].voice_observations_cap` knob (do not
      edit config/kaine.toml). Do NOT persist raw utterance text.

## 3. Tests (fakes only — no live boot)

- [x] 3.1 Internal + external utterances → one feature entry each (correct
      channel/length/word_count) + both counts incremented.
- [x] 3.2 Recorded observations contain no raw text.
- [x] 3.3 Buffer cap enforced (oldest dropped).
- [x] 3.4 JSON round-trip; a pre-change self-model (no voice fields) loads with
      zero/empty defaults.

## 4. Verify

- [x] 4.1 Full suite green — no skips/xfails added.
- [x] 4.2 `openspec validate "eidolon-voice-observation"` passes.
