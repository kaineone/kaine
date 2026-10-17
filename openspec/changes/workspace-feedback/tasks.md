## 1. Implementation

- [x] 1.1 Settings and the workspace-side controller: gains, relaxation, conflict episodes, refractory interval, the head_gain and matched_random rules (`kaine/workspace/feedback.py`)
- [x] 1.2 Top-down head, precision-weighted blend and the processors' feedback channel (`kaine/modules/feedback.py`)
- [x] 1.3 Workspace integration, boot wiring, the sequence module's published prediction and the registry injection
- [x] 1.4 Vision integration: wrapped forward model, gain on the graded intensity, feedback payload
- [x] 1.5 Audition integration on the acoustic path
- [x] 1.6 Interoception integration, residuals from the blend
- [x] 1.7 Shipped config keys with comments and the five arm study files
- [x] 1.8 Docs: global workspace, vision, audition, interoception, sequence, configuration appendix

## 2. Verification

- [x] 2.1 Bit-for-bit tests: feedback absent equals `arm = "off"` for the workspace and each processor
- [x] 2.2 Mutation checks on the blend weights, gain bounds, refractory interval and inhibited gate
- [x] 2.3 Worker first-pass review and fixes

## 3. Before the feedback ablation runs

- [ ] 3.1 Record the gains and conflict episodes in the research log, so the §6.4 stability measures (gain variance, runaway events, time to resolve) can be computed from the log
- [ ] 3.2 Preserve the top-down heads and gains through preservation and revive, as the forward models are
- [ ] 3.3 A synthetic-conflict positive control: two processors fed inconsistent but learnable inputs; the detector flags it at 0.95 and a clean control at 0.05 before any live ablation run
