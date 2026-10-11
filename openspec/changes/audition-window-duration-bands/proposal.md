## Why

Three defects in Audition, found by the mathematics review of 2026-10-08.

- **The arousal window does nothing.** The attention-driven-audition design gives hearing the audio analog of foveation: arousal narrows or widens the auditory attentional window. The code computes the window, `1 - 0.85a`, and publishes it as `attended_window`, but encodes the whole captured window regardless (`module.py` `_perceive_acoustic`). The design's task list records the window as realized; it is not.
- **The tone model measures the computer.** The speech-path forward model's feature vector includes `duration_s`, set to the wall-clock time the speech-to-text and emotion classifiers took (`module.py` `duration_s = time.monotonic() - start_time`), not the length of the utterance. Its prediction error, which can raise a neutral tone event's salience, partly tracks host load.
- **A quarter of the spectral bands are degenerate.** The fixed spectral encoder's 32 log-spaced bands start at 20 Hz; with 25 ms frames at 16 kHz the FFT bins are 40 Hz wide, so the lowest edges truncate to the same bins. Eight bands repeat a single bin (four read the DC bin), leaving 24 distinct bands.

## What Changes

- **The window is applied.** Before encoding, `_perceive_acoustic` keeps the most recent fraction `w = arousal_to_window(arousal)` of the captured window, never less than one analysis frame, and computes the energy channel on the same span. Narrowing under arousal is a shorter, more recent integration window, the temporal reading of Easterbrook narrowing; `arousal_window_min`/`max` keep the sign and range tunable. `attended_window` still reports `w`, and a new `attended_seconds` reports the span encoded.
- **Utterance duration.** The tone feature is the utterance's audio duration, `n_samples / sample_rate`, normalised over the maximum utterance length (30 s). The speech-path forward-model checkpoint carries a feature-layout tag, `utterance_duration_v2`; a checkpoint without it is discarded and the model re-learns.
- **Distinct bands.** Band edges are log-spaced bin indices forced to increase by at least one bin and to start above the DC bin, so every band covers at least one distinct FFT bin. The encoder's `model_id` becomes `spectral-logband-32-v2`, so a saved acoustic forward model trained on the old embedding is not restored onto the new one.

## Capabilities

### Modified Capabilities

- `audition-predictive`: the applied attentional window, the utterance-duration feature, and the spectral band layout.

## Impact

- **Code:** `kaine/modules/audition/{acoustic,module}.py`.
- **Behaviour:** under raised arousal the acoustic embedding covers only the most recent part of each window, so onsets dominate; acoustic alerts and arousal startles are recalibrated by the self-normalising running ratios. Tone-event salience no longer follows host latency.
- **Preserved beings:** acoustic forward models saved under `spectral-logband-32` and speech-path models without the layout tag re-learn online.
- **Docs:** `docs/09-modules/audition.md`; `openspec/changes/attention-driven-audition/tasks.md` note.
- **Paper:** §3.5 and Appendix A.2 (the tone feature vector) and A.4 (the auditory window).
