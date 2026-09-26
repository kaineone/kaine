## 1. Backend

- [ ] 1.1 `WetwarePolicyEngine` in `kaine_cl1/backends/nous.py`: silicon step first; EFE-softmax encoding per action group; per-channel firing decode, ties to silicon; feedback channels; shadow and drive modes; agreement rate logged every 100 steps; attribute forwarding to the inner engine.
- [ ] 1.2 Timed-out or errored silicon results returned unchanged, with no stimulation.

## 2. Plugin wiring

- [ ] 2.1 `boot.py`: a `nous` row injecting `engine_wrapper` (a callable taking the default engine).
- [ ] 2.2 `config.py`: optional `[nous]` table (`mode`, default `"shadow"`).
- [ ] 2.3 `plugin.py`: `nous.engine_wrapper` seam; territory minimum (two channels per action plus two feedback channels, action count taken from the wrapped engine at construction); WARNING on every boot in drive mode; Nous leaves the pending-conversion list.

## 3. Tests

- [ ] 3.1 Shadow mode returns the silicon result exactly; drive mode returns the tissue's proposal with silicon beliefs and EFE.
- [ ] 3.2 On the reference culture, a strongly favoured action is proposed on most steps.
- [ ] 3.3 Feedback pattern follows agreement.
- [ ] 3.4 Timed-out and errored results pass through without stimulation.
- [ ] 3.5 `seed_posterior` and `close` reach the inner engine.
- [ ] 3.6 Boot through KAINE's loader: Nous is built with the wrapped `PymdpEngine` (skips without the reasoning extra).

## 4. Docs

- [ ] 4.1 `docs/cl1.md`: Nous in the module table, the modes, and that on the simulator this proves wiring only.
