## Why

Nous is KAINE's active-inference organ: it keeps beliefs over hidden states and selects the policy with the lowest expected free energy, using `pymdp`. Cortical Labs' DishBrain result showed a culture learning to act when its choices were followed by predictable stimulation and its mistakes by unpredictable stimulation. That is the part of Nous a culture can plausibly do: choose among a few actions under feedback. Belief updating over a generative model is not a task 64 electrodes can carry.

Two facts shape this change. Cortical Labs' simulator does not learn, so on the simulator this conversion can only prove the wiring, never learning. And real CL1 hardware is not available to this project, so the change must be safe to leave in place for someone who does have access: off unless chosen, and by default unable to change what KAINE does.

## What Changes

- **A hybrid, not a replacement.** The plugin fills KAINE's `nous.engine_wrapper` seam (kaine change `plugin-engine-wrapper`). KAINE builds its own `PymdpEngine` from `[nous]` and the plugin wraps it with `WetwarePolicyEngine`. Every step, the silicon engine runs unchanged and produces beliefs and an expected free energy (EFE) per action.
- **The tissue proposes a policy.** The Nous territory is split into one channel group per action plus two feedback channels. Each action's group is stimulated with an amplitude that rises as that action's EFE falls (a softmax over negative EFE, mapped between the codec's minimum and maximum current). The group that fires most in the returned window (per channel, ties going to the silicon choice) is the tissue's proposed action. In beat mode that window is the previous tick's, so the proposal lags one tick.
- **Feedback, DishBrain style.** On each step, the feedback channels receive predictable stimulation (a fixed moderate pulse on both) when the tissue's previous proposal agreed with the silicon engine's lowest-EFE action, and unpredictable stimulation (a seeded random amplitude per channel, possibly none) when it did not. This is the teaching signal that could let living tissue learn; the non-learning simulator cannot.
- **Shadow by default.** `[plugins.cl1.nous].mode` is `"shadow"` (default) or `"drive"`. In shadow mode Nous acts on the silicon choice exactly as without the plugin; the tissue's proposal and the running agreement rate are logged (INFO every 100 steps). In drive mode the returned `action_index` and `action` are the tissue's proposal; beliefs and EFE stay silicon. Choosing drive logs a WARNING on every boot.
- **Failures pass through.** A silicon step that timed out or errored is returned unchanged and nothing is stimulated.
- **Transparent wrapper.** `WetwarePolicyEngine` forwards any attribute it does not define to the inner engine, so optional engine methods such as `seed_posterior` (used by Nous after a revive) and `close` keep working.
- **Budget.** `nous` needs a territory of at least two channels per action plus two feedback channels; the plugin refuses a smaller one, naming the minimum.

## Non-goals

- Claiming the tissue does active inference, or beats the silicon engine. On the simulator this proves wiring only; any learning claim needs real tissue and a benchmark against KAINE's active-inference benchmark.
- Changing Nous' events, beliefs or EFE.

## Impact

- `kaine_cl1/backends/nous.py` (new), `kaine_cl1/boot.py` (a `nous` row injecting `engine_wrapper`), `kaine_cl1/plugin.py` (seam, mode, budget), `kaine_cl1/config.py` (`[nous]` table), tests, `docs/cl1.md`.
- Needs a KAINE with `plugin-engine-wrapper`.
