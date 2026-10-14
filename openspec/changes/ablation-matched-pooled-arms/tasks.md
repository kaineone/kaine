## 1. Implementation

- [x] 1.1 The workspace takes an arm and a seed; matched draw and pooled broadcast; arm in metadata
- [x] 1.2 The context adopts an empty pooled broadcast
- [x] 1.3 The research log's workspace record copies the arm
- [x] 1.4 The cycle reads `[workspace].arm` and seeds the draw from the run seed; `config/kaine.toml` documents the key
- [x] 1.5 The study overlay pins greedy decoding and the competitive arm
- [x] 1.6 Tests for each arm, the default, reproducibility, the context and the overlay

## 2. Review fixes

- [x] 2.1 The `[workspace]` key guard accepts `arm`; boot-path tests on the shipped and study configurations
- [x] 2.2 The matched arm refuses a context without the broadcast flag
- [x] 2.3 The language module's cache ignores an empty broadcast
- [x] 2.4 Engine-level tests: matched draws only on broadcast ticks; pooled publishes only broadcast ticks
- [x] 2.5 Greedy decoding out of `thesis_test`; the study layer and the three workspace-mediation study configurations
- [x] 2.6 Docs and specs: the study layer, how an ablation run selects its arm, the unpersisted matched generator, sampling in general use
- [x] 2.7 The individuation probe decodes at its own `[individuation].probe_temperature`
- [x] 2.8 The run context and manifest record the study; study files are limited to four tables
- [x] 2.9 Docs: which entry points load a study, and running lifecycle and revive commands under the run's study
