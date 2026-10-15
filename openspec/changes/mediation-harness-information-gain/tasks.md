## 1. Harness

- [x] 1.1 `measures.py`: keep the sign test; add the per-processor mean gain over included reports after the initial learning period and the headline over processors (undefined when any processor's is); remove the correlation and entropy measures.
- [x] 1.2 `pooled.py` replaces `conditioning.py`: the pooled snapshot holds every candidate, carries no access threshold and is never inhibited.
- [x] 1.3 `stimulus.py`: seeded batteries for the interoception module's metrics, the vision module's frames (through a vector encoder double) and background candidates; a coupled battery and an independent one.
- [x] 1.4 `runner.py`: run the workspace-on and pooled arms over real interoception and vision modules with the same seeds; read `context_gain` per report; compute `IG_j`, `IG` and `dIG`; classify WIN, NULL, NEGATIVE or NOT EXERCISED.
- [x] 1.5 `stability.py` and `__main__.py` use the new headline and options.
- [x] 1.6 Delete `inject.py` and its test, and the stale exemption for it.

## 2. Suite

- [x] 2.1 `suite.py`: collect per-seed `dIG`, apply the two one-sided sign tests with the strict alpha rule, keep the WIN p-value in the Holm family, and say in every verdict that the harness does not test the hypothesis.

## 3. Tests

- [x] 3.1 Measures, pooled snapshot and verdict classification, including NOT EXERCISED.
- [x] 3.2 Runner: same seed reproduces the records and verdict; both arms and both processors give a defined gain on the coupled battery; competition operates; no network connection is opened.
- [x] 3.3 Suite aggregation, with the strict alpha cases kept.

## 4. Docs and checks

- [x] 4.1 Docs pages describing the harness.
- [x] 4.2 `openspec validate mediation-harness-information-gain --strict`; preflight gate green.
