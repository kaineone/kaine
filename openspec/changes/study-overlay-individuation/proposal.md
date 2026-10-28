## Why

The real ignition study run (seed-2026-10) halted at development step 0 with `failed:exit:5`: the child cycle refused to boot because the research safety-net gate found the individuation producer disabled. The study overlay promises to enable the safety net on every step but never set `[individuation].enabled`, and `config/kaine.toml` ships it `false`. The research gate gained the individuation requirement after the overlay was written. Test boots passed only because their throwaway operator config set it, and the runner's dry runs used a stand-in cycle that never reached the real gate.

## What Changes

- The study overlay sets `[individuation].enabled = true` on every step, overriding the operator config like the other safety-net keys. The shipped individuation defaults (empty `battery_path`, the other keys) validate, so the gate's "config is invalid" arm cannot fire from them.
- Gate requirements and their coverage: preservation, welfare response and logging were already set; encryption is satisfied by the shipped `[security.state_encryption].enabled = true`; the self-check needs no config; the state key and Redis password stay operator-supplied and are not faked.
- `kaine/cycle/research_gate.py` gains `config_requirements(config)`, the pure config-level half of `evaluate_safety_net`, with identical behaviour.
- A test builds the real merged config of each step kind (shipped config plus study overlay, no operator overlay) and asserts every config requirement passes.
- The study doc lists individuation among the keys the overlay enables.

## Impact

- `kaine/research/ignition_study/overlay.py`, `kaine/cycle/research_gate.py`, `docs/15-experiments/ignition-study.md`, one new test.
- Prior work: module-ignition-study tasks 2.2 to 2.11, the research gate and the individuation change in the archive.
