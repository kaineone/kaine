## Why

`KAINE_Paper_v4.md` §5.6 / §7.4 specify a **statistically operationalized
individuation boundary** for forks: at a fork's pre-designated merge point, the
operator assesses whether the fork has formed independent cognitive identity
before reintegrating. The challenge is distinguishing genuine preference formation
from the LLM's stochastic variation. The paper's method: present fork and parent a
preference-elicitation battery under controlled conditions; compare divergence
against a **null distribution** built from running the parent repeatedly with
varied seeds; if the fork's divergence exceeds the **95th percentile** of the
null, it is statistically significant. The framework gives Guardians evidence, not
a verdict. No such instrument exists today (fork/merge exists, individuation
assessment does not).

## What Changes

- `kaine/evaluation/individuation.py`: a `IndividuationTest` that, given a fork and
  parent (or their elicitation transcripts) and a preference-prompt battery:
  - builds the null distribution by sampling parent-vs-parent divergence across N
    varied seeds (controlled temperature/seed where possible);
  - computes the fork-vs-parent divergence with the same metric (embedding cosine
    distance, reusing the A/B-divergence embedding path);
  - runs a permutation test and reports whether fork divergence exceeds the
    configured percentile (default 95th), with the p-value and the null summary.
- A bundled default preference battery (`kaine/evaluation/preference_battery.py`),
  operator-extensible.
- Output is an evidence report (JSONL + summary) for the Guardian decision; the
  instrument **decides nothing** about sovereignty (that is governance, §7.4).
- `[evaluation.individuation]` config: `null_samples`, `significance_percentile`,
  `metric`, `battery_path`.

## Capabilities

### New Capabilities

- `individuation-boundary`: permutation-test instrument quantifying fork-vs-parent
  preference divergence against a parent stochastic-variation null.

### Modified Capabilities

None.

## Impact

- **Depends on:** `evaluation-sidecar` (reuses the embedding/divergence path),
  `adapter-ties-dare-merge` (fork/merge provides the subjects).
- **Repo:** adds `kaine/evaluation/individuation.py`, `preference_battery.py`,
  tests; `config/kaine.toml`.
- **Governance:** produces evidence for Guardians (paper §7.4); not an automated
  sovereignty gate. Operator-run at a merge point.
