## 1. Paper (first)

- [ ] 1.1 Paper change: where per-tick motor control sits relative to the workspace (§3.3, §3.6), the motor-contingency learner and its cited basis, body-declared freeze-then-free stages, the motor prediction error as a report (§4, an appendix entry and Table A1), and the embodiment step in §6.5. Starts only when the start condition in the proposal holds.

## 2. Code (after 1.1)

- [ ] 2.1 The motor driving loop that calls the control surface each control tick and feeds back the body's proprioception, gated by inhibition, with tests that the build with the control surface off is bit for bit identical.
- [ ] 2.2 The learner at the motor-policy seam and the body-declared stages, with tests that the curriculum frees each stage only on demonstrated competence.
- [ ] 2.3 The motor prediction error as a precision-scaled report, with tests.
- [ ] 2.4 A pan-tilt camera body adapter, and the docs (`docs/09-modules/embodiment.md`, `config/kaine.toml` comments).

## 3. Study (after 2)

- [ ] 3.1 The embodiment branch of the module-addition study, from the preserved seed.
