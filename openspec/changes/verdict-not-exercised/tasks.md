## 1. Shared vocabulary

- [x] 1.1 `kaine/experiment/verdict.py`: add `Outcome.NOT_EXERCISED` with the paper's meaning in the docstring.
- [x] 1.2 Test: the outcome set includes `NOT_EXERCISED` and it serialises to `"NOT_EXERCISED"`.

## 2. Harness and suite

- [x] 2.1 `runner.py`: an unexercised run returns `Outcome.NOT_EXERCISED` with its reason; the redundant flag leaves the verdict metrics.
- [x] 2.2 `suite.py`: unexercised seeds stay out of the sign tests; the aggregate is NOT_EXERCISED when no seed is exercised; such an experiment stays out of the Holm family and is listed under `not_exercised`; the printed report names it. The same rule for an individuation result passed in as NOT_EXERCISED.
- [x] 2.3 Tests: classification, seed exclusion, the aggregate, and the family view with and without an unexercised experiment.

## 3. Retire the minimal profile

- [x] 3.1 Delete `config/profiles/minimal_experiment.toml`.
- [x] 3.2 Replace its test with a reduced-module-set boot test that sets the modules in code.
- [x] 3.3 Configuration appendix: drop the profile from the overlay table and the per-key notes.

## 4. Docs and checks

- [x] 4.1 Experiments, run-identity and verification pages describe NOT EXERCISED and the suite's handling.
- [x] 4.2 ROADMAP row; `openspec validate verdict-not-exercised --strict`; preflight gate green.
