## Why

The revised paper (predictive-workspace-paper #21, decision D11, rounds R2, R3, R6 and R7; Appendix A.1, A.2, A.5 and A.8) makes the accessed content of the workspace the prediction context of the perceptual and interoceptive processors, as global workspace theory and the predictive global neuronal workspace require. In the code only Chronos reads the broadcast (as its input) and Thymos appraises it; Topos, Audition and Soma never read it, so the workspace cannot influence perception and the planned test's measure is undefined.

## What Changes

This change lands in three pull requests.

1. **Context plumbing (this PR).** A new `kaine/modules/context.py` computes the paper's featurization `Phi_I(X, age, 0)` of a set of events weighted by intensity (24 components, the same source bins and type hash as Chronos's featurizer), and a `BroadcastContext` holder that adopts an accessed broadcast (members whose score reaches the access threshold), ignores inhibited ones, reports the context with its current age, and keeps running sums of each source's share so that the null context of the information-gain measure can be computed (A.8). Syneidesis records its access threshold in each broadcast's metadata so modules can tell accessed members from riders.
2. **Topos and Audition forward models take the context** as an extra input, adopt it from the broadcast stream, and compute the null-context prediction for the information gain; checkpoints without context weights restore with zero context weights.
3. **Soma's readout takes the context** the same way, with the language organ's share kept in Soma's null context.

## Capabilities

### Modified Capabilities

- `syneidesis`: broadcasts carry the access threshold; accessed members are those whose score reaches it.

## Impact

- **Code:** new `kaine/modules/context.py`; `kaine/workspace/syneidesis.py` (metadata only) in this PR.
- **Behaviour:** none in this PR; later PRs make the processors condition on the context.
