## 1. Implementation

- [ ] 1.1 Settings and the workspace-side controller: gains, relaxation, conflict episodes, refractory interval, the head_gain and matched_random rules (`kaine/workspace/feedback.py`)
- [ ] 1.2 Top-down head, precision-weighted blend and the processors' feedback channel (`kaine/modules/feedback.py`)
- [ ] 1.3 Workspace integration, boot wiring, the sequence module's published prediction and the registry injection
- [ ] 1.4 Vision integration: wrapped forward model, gain on the graded intensity, feedback payload
- [ ] 1.5 Audition integration on the acoustic path
- [ ] 1.6 Interoception integration, residuals from the blend
- [ ] 1.7 Shipped config keys with comments and the five arm study files
- [ ] 1.8 Docs: global workspace, vision, audition, interoception, sequence, configuration appendix

## 2. Verification

- [ ] 2.1 Bit-for-bit tests: feedback absent equals `arm = "off"` for the workspace and each processor
- [ ] 2.2 Mutation checks on the blend weights, gain bounds, refractory interval and inhibited gate
- [ ] 2.3 Worker first-pass review and fixes
