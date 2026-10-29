## Why

funasr opens a tqdm progress bar on every `AutoModel.generate()` call unless the model is built with `disable_pbar`. The audition module classifies vocal emotion once per heard audio window, so the tenth test boot wrote about 30 MB of progress bars to the cycle log in 8 hours, burying the log lines an operator reads.

## What Changes

- `Emotion2vecClassifier` builds its funasr `AutoModel` with `disable_pbar=True`, next to the `disable_update=True` it already passes. In funasr 1.4.16, the version the container installs, `AutoModel.inference` reads this constructor argument to decide whether to open a bar.
- Classification inputs, outputs and degradation paths are unchanged.

## Capabilities

### Modified Capabilities

- `audio-input`: the emotion classifier keeps funasr's progress bars out of the log.

## Impact

- `kaine/modules/audition/emotion.py`, `tests/test_audition_emotion.py`, `docs/09-modules/audition.md`.
- Behaviour: none for the entity. The cycle log loses the per-call progress bars.
