## 1. Core

- [ ] 1.1 `kaine/plugins.py`: `nous.engine_wrapper` in `INJECTABLE_SEAMS`; refuse `nous.engine` together with `nous.engine_wrapper`.
- [ ] 1.2 `kaine/boot.py` `make_nous`: build the default engine, call the wrapper, check the result against `ActiveInferenceEngine`.

## 2. Tests

- [ ] 2.1 The wrapper receives a `PymdpEngine` built from `[nous]` and its result is used.
- [ ] 2.2 A non-engine return fails naming the plugin.
- [ ] 2.3 Both seams filled fails naming the plugins.
- [ ] 2.4 Spot's rebuild calls the wrapper again with a fresh default engine.

## 3. Docs

- [ ] 3.1 `docs/plugins.md`: the seam table and when to wrap rather than replace.
