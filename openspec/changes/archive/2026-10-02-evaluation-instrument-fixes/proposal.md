# Evaluation instruments record what they claim to

## Why
A documentation audit against the code found two evaluation instruments that never produce the data they exist for:

- **The voice-alignment divergence observer writes empty records.** It reads `pairs_processed`, `dpo_loss`, the capability scores and the similarity means from the `voice_alignment` sub-dictionary of `hypnos.sleep.completed`, but Hypnos puts those fields at the top level of the summary; the sub-dictionary holds only `accepted`, `adapter_path`, `capability_loss`, `reason` and `samples_used`. Every record is null apart from its id and timestamp. It also writes one of these records every sleep when voice alignment is switched off, although its documentation says it skips them.
- **The live oscillatory ablation cannot be switched on.** `[evaluation].oscillatory_ablation` is a field of `EvaluationConfig`, documented in the cycle as the switch for the dual-path ablation recorder, but `EvaluationConfig.from_mapping` never reads it, so it is always `False`.

A third audit item was checked and is not a bug: the raw bus archive and Nexus diagnostics follow `lingua.out`, which Lingua does publish as a mirror of every utterance. Only a comment in `raw_bus_archive_consumer.py` says otherwise; it is corrected.

Research impact: instrument only. The entity's behaviour does not change. Runs from this version on record complete voice-alignment outcomes (earlier runs' records of this observer are null, never wrong), and can record the live ablation when a run enables it. The running module-ignition study is unaffected (pinned image).

## What changes
- `VoiceAlignmentDivergenceObserver` reads the summary as Hypnos writes it: the gate outcome (`accepted`, `capability_loss`, `samples_used`, and a fixed outcome category derived from `reason`: `accepted`, `no_pairs`, `vetoed_abliteration`, `vetoed_capability` or `failed`) from the `voice_alignment` sub-dictionary. The free-text reason is never recorded: these records go into the metrics-only research bundle, and reasons can contain exception text and local paths, and the training metrics (`dpo_loss`, capability scores before and after, similarity means before and after) from the top level. It writes no record when the voice-alignment phase was skipped by its gates (the phase result carries `skipped`), and still writes one when the phase ran and found no pairs.
- `EvaluationConfig.from_mapping` reads `oscillatory_ablation` (boolean, default `false`).
- The `lingua.out` comment in the raw archive consumer is corrected.

## Impact
- Code: `kaine/evaluation/observers/voice_alignment_divergence_observer.py`, `kaine/evaluation/config.py`, `kaine/evaluation/observers/raw_bus_archive_consumer.py` (comment).
- Specs: `evaluation-observers`, `evaluation-sidecar` (ADDED).
- Docs: the research-data chapter's observer list and the configuration appendix stop describing the ablation switch as unread.
