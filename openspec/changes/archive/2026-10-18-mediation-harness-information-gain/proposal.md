## Why

The offline development harness of the workspace-mediation test (`kaine/evaluation/benchmarks/workspace_mediation_ablation/`) still measures what the paper retired. Its primary measure is the correlation between the interoception module's and the sequence module's error series, its secondary measure is the divergence of the language organ's conditioning, and it ships a tool that injects an utterance and reads the organ's reply. The paper now says the language organ's utterances are not a measure (§3.5, §6.3) and that the primary measure is the cross-module broadcast information gain (§6.3, Appendix A.8). Section 5.4 says the harness "runs a reduced pair of modules against a pooled arm only; it is development tooling, is to be rebuilt around the information-gain measure, and does not test the hypothesis."

## What Changes

- **The harness measures information gain.** It drives a reduced pair of real context-conditioned processors, the interoception and vision modules, through two arms with the same seeds and stimulus. Each processor evaluates its forward model with the context it holds and with the null context of Appendix A.8 and publishes the per-report gain (`context_gain`), as the shipped modules already do. The harness reads that gain, averages it per processor over the included reports after an initial learning period (`IG_j`), averages the two processors (`IG`), and reports the run contrast `dIG`, the workspace-on headline minus the pooled one.
- **Pooled arm.** Every candidate of a tick enters the context, weighted by its intensity, with no scoring, selection or access gate. The workspace-on arm uses the workspace as built with a capacity below the per-tick candidate count, so selection excludes.
- **Verdict.** WIN, NULL or NEGATIVE by `dIG` against a minimum effect. A run in which competition never operated, no broadcast was accessed, or the gain is undefined is NOT EXERCISED, reported as NULL with an explicit flag because the shared verdict vocabulary has no NOT EXERCISED member yet. Every verdict says the harness is development tooling and does not test the hypothesis.
- **Suite.** The suite runs the harness over several seeds and applies the two one-sided sign tests of Appendix A.8 to the per-seed `dIG` (WIN on `dIG - min_effect`, NEGATIVE on `-min_effect - dIG`), keeping the strict `p < alpha` rule. The WIN test's p-value stays in the Holm family.
- **Retired measures removed.** The coupling correlation, the coalition-source entropy, the conditioning divergence, the flat fan-in conditioning path that rendered for the organ, and the utterance injection tool (`inject.py`) are deleted with their tests.
- **Docs.** The pages that describe the harness say what it now does and that it does not test the hypothesis.

The information-gain aggregation (`IG_j`, the headline `IG`, and the sign tests) lives in the benchmark package. The live analysis of the planned test will need the same aggregation; it stays local here so this change does not touch `kaine/cycle` or `kaine/modules/context.py`, which other changes are editing.

## Capabilities

### Modified Capabilities

- `workspace-mediation-ablation`: the offline harness's arms, measure, verdict and suite aggregation.

## Impact

- **Code:** `kaine/evaluation/benchmarks/workspace_mediation_ablation/` (rewritten; `conditioning.py` replaced by `pooled.py`; `inject.py` deleted), `kaine/evaluation/benchmarks/suite.py`.
- **Tests:** `tests/test_workspace_mediation_measures.py`, `tests/test_workspace_mediation_runner.py`, `tests/test_suite_strict_alpha.py` rewritten; `tests/test_workspace_mediation_inject.py` deleted; the stale `inject.py` exemption leaves `tests/test_cursors_advance_past_undecodable.py`.
- **Behaviour:** offline only. No module, cycle or context code changes, and nothing boots an entity or opens a network connection.
- **Docs:** `docs/15-experiments/README.md`, `docs/14-for-researchers.md`, `docs/18-verification.md`, `docs/19-plugins-and-cl1.md`, and `docs/02-architecture/README.md` (one fewer exempt bus reader).
- **Paper:** none; this follows §5.4, §6.3, §6.4 and Appendix A.8.
