## 1. Backend

- [x] 1.1 `WetwarePolicyEngine` in `kaine_cl1/backends/nous.py`: silicon step first; EFE-softmax encoding per action group; per-channel firing decode, ties to silicon; feedback channels; shadow and drive modes; agreement rate logged every 100 steps; attribute forwarding to the inner engine.
- [x] 1.2 Timed-out or errored silicon results returned unchanged, with no stimulation.

## 2. Plugin wiring

- [x] 2.1 `boot.py`: a `nous` row injecting `engine_wrapper` (a callable taking the default engine).
- [x] 2.2 `config.py`: optional `[nous]` table (`mode`, default `"shadow"`).
- [x] 2.3 `plugin.py`: `nous.engine_wrapper` seam; territory minimum (two channels per action plus two feedback channels, action count taken from the wrapped engine at construction); WARNING on every boot in drive mode; Nous leaves the pending-conversion list.
- [x] 2.4 `substrate/broker.py`: synchronous (pre-beat) windows and `start_beat` serialised by a re-entrant lock, since Nous steps in a worker thread.
- [x] 2.5 `substrate/broker.py`: tagged exchange; a module reads the response window to its own most recent tagged stimulation, labelled with that tag, so Nous scores the tissue against the silicon choice it encoded even when it steps less often than the cycle ticks.

## 3. Tests

- [x] 3.1 Shadow mode returns the silicon result exactly; drive mode returns the tissue's proposal with silicon beliefs and EFE.
- [x] 3.2 On the reference culture, a strongly favoured action is proposed on most steps.
- [x] 3.3 Feedback pattern follows agreement.
- [x] 3.4 Timed-out and errored results pass through without stimulation.
- [x] 3.5 `seed_posterior` and `close` reach the inner engine.
- [x] 3.6 Boot through KAINE's loader: Nous is built with the wrapped `PymdpEngine` (skips without the reasoning extra).

## 4. Docs

- [x] 4.1 `docs/cl1.md`: Nous in the module table, the modes, and that on the simulator this proves wiring only.
