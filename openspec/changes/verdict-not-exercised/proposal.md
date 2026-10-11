## Why

The paper resolves comparisons to WIN, NULL, NEGATIVE or NOT EXERCISED (§6.3, §6.6, Appendix A.8). A run is NOT EXERCISED when competition never operated in the workspace-on arm, when that arm had no accessed broadcast, or when its contrast is undefined, and the verdict against a control is NOT EXERCISED when no run was exercised. The shared vocabulary in `kaine/experiment/verdict.py` has no such member, so the workspace-mediation development harness reports NULL with a `not_exercised` flag. A reader of the outcome alone sees a null where no comparison took place, and the suite enters a sign-test p-value of 1.0 for an experiment that ran no test into its Holm family.

The suite also collects every seed's `dIG` into the sign tests, including a seed in which competition never operated but the gain happened to be defined. Appendix A.8 puts only runs that are not NOT EXERCISED into the tests.

Separately, `config/profiles/minimal_experiment.toml` still calls itself "the workspace-mediation ablation configuration": Soma, Chronos and Lingua with a lowered `top_k` and greedy decoding, built for an output-divergence measure the paper has retired. The planned test now runs the base-thesis form in the three arms of §6.3, and the paper says a system limited to substrate telemetry and event timing offers too little diversity for competition to matter (§1). Nothing loads the profile except its own test, the utterance-injection tool its spec describes was deleted with the old harness, and no operator guide tells anyone to use it.

## What Changes

- **Shared vocabulary.** `Outcome` gains `NOT_EXERCISED`, serialised as `"NOT_EXERCISED"`. It means the comparison did not take place, so it is neither a WIN nor a NULL and is not evidence in either direction.
- **Harness.** A run that is not exercised returns `Outcome.NOT_EXERCISED` with its reason in the detail and in `metrics["not_exercised_reason"]`. The redundant `not_exercised` flag leaves the verdict's metrics.
- **Suite aggregation.** Seeds that are not exercised are left out of the two sign tests, whatever their `dIG`. The suite verdict is NOT EXERCISED when no seed was exercised, and its metrics say how many seeds were and were not.
- **Holm family.** An experiment whose verdict is NOT EXERCISED has run no test and has no p-value, so it does not enter the Holm family. The family view lists it by name under `not_exercised`, and the printed report says so. The same rule applies to an individuation result passed in with a NOT EXERCISED verdict.
- **Retire `minimal_experiment`.** The profile is deleted. Its boot test is kept as a test that a reduced module set (Soma, Chronos and Lingua, set in code) builds without any disabled-module dependency and that re-enabling a module is a toggle. The configuration appendix stops listing the profile. The `minimal-run-configuration` capability keeps only the reduced-set boot requirement.
- **Docs.** The experiments pages, the run-identity page and the verification page describe the new outcome and how the suite treats it.

## Capabilities

### Modified Capabilities

- `experiment-foundation`: the shared verdict schema gains NOT EXERCISED; the suite's family-wise view leaves out experiments that are not exercised.
- `workspace-mediation-ablation`: the harness and its suite aggregation report NOT EXERCISED as its own outcome and keep unexercised seeds out of the sign tests.
- `minimal-run-configuration`: the minimal experiment profile, its competition requirement and the utterance-injection requirement are removed; the reduced-set boot requirement stays.

## Impact

- **Code:** `kaine/experiment/verdict.py`, `kaine/evaluation/benchmarks/workspace_mediation_ablation/runner.py`, `kaine/evaluation/benchmarks/suite.py`. No change to `kaine/cycle`, `kaine/modules` or `kaine/workspace`.
- **Config:** `config/profiles/minimal_experiment.toml` deleted.
- **Tests:** `tests/test_experiment_foundation.py`, `tests/test_workspace_mediation_runner.py`, `tests/test_suite_strict_alpha.py`, `tests/test_evaluation_suite.py`; `tests/test_minimal_experiment_profile.py` becomes `tests/test_reduced_module_set_boot.py`.
- **Behaviour:** offline only. A suite report can now carry `"NOT_EXERCISED"` as an experiment outcome and a `not_exercised` list in its family-wise view. A reader that assumed the comparative outcomes were exactly WIN, NULL and NEGATIVE must handle the new value. Nothing in the repository branches on the full set: the stability harness counts it as a distinct outcome, so a mix of exercised and unexercised seeds reads as unstable, which is the honest report.
- **Docs:** `docs/14-for-researchers.md`, `docs/15-experiments/README.md`, `docs/16-run-identity.md`, `docs/18-verification.md`, `docs/appendix-a-configuration/README.md`, `docs/appendix-a-configuration/core.md`, `docs/appendix-a-configuration/modules.md`.
- **Paper:** none. Appendix A.8 says "the runs with a defined contrast enter" the sign tests; this change reads "defined contrast" as "not NOT EXERCISED", which §6.3 requires (a run with no competition gives NOT EXERCISED even when its gain is defined). The paper does not say whether an experiment that is NOT EXERCISED enters the offline suite's Holm family; it says Holm-adjusted values are reported beside each experiment's own verdict, and an experiment with no test has no value to adjust.
