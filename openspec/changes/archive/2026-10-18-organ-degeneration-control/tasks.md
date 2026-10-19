## 1. Implementation

- [x] 1.1 Client: a DRY penalty on `ChatRequest`, sent as the four llama.cpp fields only when its multiplier is above 0, ignored by the in-process backend
- [x] 1.2 Sentence cut: a pure function that cuts text before its first verbatim repeated sentence of at least three words, or back to its last complete sentence when the token cap stopped it
- [x] 1.3 Language module and factory: `think_max_tokens`, the DRY keys and `sentence_cut`, validated, applied to speak and think generation and never to the probe; the cut is logged content-free and recorded in `extra.text_cut`
- [x] 1.4 Config, docs and tests: shipped values in `config/kaine.toml`, module and configuration docs, offline measurement on the pinned build
