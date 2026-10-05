## 1. Interaction counting

- [ ] 1.1 Move the operator-source list to one shared constant importable by `kaine.workspace.volition`, `kaine.modules.empatheia` and `kaine.modules.chronos` within the import-linter contracts. Point both existing copies at it.
- [ ] 1.2 Chronos resets the interaction clock only for speech-path events (`audition.transcription` with non-empty text, `audition.emotion`) from an operator source. Add `[chronos].interaction_event_types` to the factory's allowed keys.
- [ ] 1.3 Tests through the real bus decoding path:
  - `audition.perception` from `live_mic` does not reset the clock;
  - `audition.emotion` from `playlist` does not reset it;
  - `audition.emotion` from `live_mic` with transcription off does;
  - an empty transcription does not.

  Mutation-check each one.

## 2. Featurizer layout

- [ ] 2.1 A versioned layout in `SnapshotFeaturizer`. Layout 1 is today's mapping; layout 2 puts `audition` in slot 23. The default for a new featurizer is the newest layout.
- [ ] 2.2 Chronos records the layout in `serialize()`. `deserialize()` restores it, treats an absent key as layout 1 with one log line, and refuses an unknown number.
- [ ] 2.3 Tests:
  - a layout-1 snapshot revives on layout 1 and featurizes an Audition event into the overflow bin;
  - a new Chronos featurizes it into slot 23;
  - the vector length is 24 under both;
  - restore works in either order relative to `initialize()`.

## 3. Profile and spec

- [ ] 3.1 `config/profiles/thesis_test.toml` sets `[chronos].forward_prediction = true` (ping the integrator first). `config/kaine.toml` keeps it false.
- [ ] 3.2 A seeded offline check, with no entity boot: drive Chronos with a recorded-shape broadcast sequence and confirm `temporal_prediction_error` is non-zero and its salience is calibrated against the rolling window.
- [ ] 3.3 Update `docs/09-modules/chronos.md` for the interaction rule and the layout.
- [ ] 3.4 `openspec validate chronos-forward-model-on --strict`.
