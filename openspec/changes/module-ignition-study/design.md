# Design — `module-ignition-study`

## Steps and lines

- **Step order:**
  1. seed (gestation);
  2. branch 0;
  3. repeat;
  4. then, for k = 1…9, branch k followed by accumulate k.

  One start at a time.
- **The seed.** A gestation run with staging on, the local womb and automatic birth (`require_operator_ack_for_birth = false`).
  - When `runtime.json` reports the embodied stage, the runner waits until the birth bloom has completed (the womb reports born), then requests a preservation with stop.
  - That preservation is the seed, S. The stage file in S carries the womb's time at birth.
- **Branch k.** Revive S with the base set plus `order[:k]`.
- **Repeat.** Revive S with the base set, exactly as branch 0.
- **Accumulate k (k ≥ 1).** Step 1 revives branch 0's preservation. Each later step revives accumulate k−1's preservation, with the base set plus `order[:k]`.
- **Each viewing.** Mode `playlist` with the four-film manifest, the transition at the start, and preserve-and-stop at the end. The runner records the step manifest: line, step, module set, start bundle, preservation, run id and the recording paths.

## Isolation

- **Working directory.** Every state path is relative to the working directory. Each branch and repeat run therefore runs from its own directory, `studies/<id>/branch/<k>/` and `studies/<id>/repeat/`, and the accumulate line from `studies/<id>/accumulate/`.
- **Memory collections.** Collection prefixes are per branch step, per repeat, and per accumulate line. A revive restores the bundle's memories into the run's own collections.
- **Bus.** Every step starts on an empty, dedicated bus database. The runner owns only the study's database numbers, which must differ from the operator's, and flushes that database before the step starts.

## Hosting

- **Inside the cycle image.** The runner runs as a compose service from the cycle image, with the operator config, the secrets file and the media overlay mounted exactly as for `kaine-cycle`.
  - Each step's cycle is a subprocess in that container.
  - The bus and the organ are reached by service name, and the models from `/models`.
- **Durable storage.** The study directory is a durable volume on the operator's chosen storage. Preservations land under the study directory, never in the container's writable layer.

## Recording and privacy

- **Every run persists:**
  - the research event log (content-free);
  - the workspace trajectory (content-scrubbed);
  - the film-aligned ignition log;
  - a record of every stream Nexus displays, after the same privacy filter Nexus applies;
  - Lingua's external utterances (local only, never export-eligible).
- **Inner speech** (`lingua.internal`, `internal_speech`) is never recorded. See `run-recording`.
- **Raw sense data is never persisted.** The raw bus archive stays off.

## Ignition analysis

- **Per viewing:** the living spec's content-free measures.
- **Comparisons:**
  - branch k − branch 0 (a faculty's effect from the seed);
  - branch 0 − repeat (the noise floor, one sample);
  - accumulate k − branch k (familiarity and history);
  - the film-minute profiles of all runs.
- **Output** is content-free.
- **Claude Science** receives only the metrics-only bundle, with operator consent.

## What this study cannot show

- **One being per condition.** Every comparison is n = 1, and the noise floor comes from one repeat. Differences smaller than the repeat's are not evidence of anything.
- **Branch k adds modules in a fixed order.** Its effect is the k-th module's effect given the modules before it, not in isolation.
- **The accumulate line mixes familiarity with module history.** No line rewatches without gaining modules.
- **Faculties without an input channel on this host are expected nulls:** Praxis without effectors, Perception without locus requests, and Mundus without an approved body.
- **Vox needs a speech backend** that fits beside Topos, so the study uses the CPU backend.
