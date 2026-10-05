## Why

The paper grounds Chronos in thalamo-cortico-striatal interval timing (Buhusi and Meck 2005). That mechanism's behavioural signature is the **scalar property**: timing variability grows in proportion to the interval timed, which is Weber's law for time. Chronos's CfC reservoir is a generic learner and nothing guarantees the property (alternatives review 2026-10-05, §5.1).

The emergence-friendly route is to keep the generic learner and **test** it. A recent benchmark (arXiv 2608.16666) shows a CTRNN baseline fails the scalar variance test, which makes it a ready falsification test for Chronos.

**Design document only.** This change defines the test. Whether Chronos passes, and what to do if it fails, follows the workspace-mediation ablation.

## What Changes

A design for an offline scalar-property test of Chronos, and the two candidate mechanisms from the cited lineage if it fails.

## Impact

- Code: none in this change.
- Licence: the Howard-lab Laplace time-cell code (DeepSITH, SITHCon) has no licence, so it is reimplemented from the papers if ever needed.
