## Why

`KAINE_Paper_v4.md` §3.3.2 introduces **Phantasia**, the world-model / imagination
module: during waking it predicts future external states and publishes world-
prediction errors; during offline consolidation it generates predicted scenario
extensions from replayed memories ("what might have happened next"). The paper
scopes DreamerV3 as future work, but the operator has elected to **pull DreamerV3
forward into this change** as Phantasia's world-model core, using the official
**danijar/dreamerv3** (MIT-licensed, JAX-based, actively maintained) rather than
hand-rolling a forward model.

Phantasia is the twelfth module and a prerequisite for the Hypnos phase-3
associative-replay scenario generation (`hypnos-restructure`).

## What Changes

- **Vendor danijar/dreamerv3** under `external/dreamerv3/` at a recorded upstream
  commit hash (SPDX: MIT). The upstream codebase is a run-as-script research
  project (deps: jax, chex, einops, elements, embodied) — not a clean pip library.
  We vendor the relevant source and extract only the **RSSM world-model core**
  (recurrent + stochastic latent transition, encoder, decoder, imagination rollout).
  The actor, critic, and return heads are **excluded**.

- New module package `kaine/modules/phantasia/`:
  - `world_model.py` — `WorldModel` protocol + `DreamerWorldModel` wrapping the
    vendored RSSM core. A `FakeWorldModel` allows tests to run without JAX or the
    vendored code.
  - `encoder.py` — maps a `WorkspaceSnapshot` to the world model's observation
    vector (salience-weighted coalition + affect summary + inhibition flag).
  - `module.py` — `Phantasia(BaseModule)`.
    - **Waking (inference):** each tick, predict the next latent, publish
      `phantasia.world_error` (prediction-error salience signal into the workspace).
    - **Offline (Hypnos):** on a `mnemos.replay` cue, roll out imagined trajectories
      from the seed memory and publish `phantasia.scenario`. `phantasia.scenario` is
      re-injected into the workspace broadcast during maintenance so Nous, Thymos,
      and Eidolon process it via `on_workspace` (associative consolidation, paper
      §3.3.5 phase 3). Training on the accumulated trajectory buffer runs during
      this window and is gated by `training_enabled`.

- **Zero-persistence:** training is in-memory only. The trajectory buffer is never
  serialized to disk. Any disk-serialization hooks in the upstream vendored code are
  bypassed. No `.pt`, `.pkl`, `.npy`, `.arrow`, or `.jsonl` files are written to
  `/tmp` or the project directory during a training pass.

- `[phantasia]` config + `[modules].phantasia = false`; `make_phantasia` factory.
  JAX added as `jax[cpu]` in the `[worldmodel]` optional extra (`pyproject.toml`).

- **Depends-on:** `mnemos-replay` (offline path is cued by `mnemos.replay`; without
  it the offline scenario-generation path is silently dead).

## Capabilities

### New Capabilities

- `phantasia`: danijar/dreamerv3 RSSM world model over workspace trajectories —
  waking world-prediction error, offline imagined-scenario generation re-injected
  into the workspace broadcast, sleep-time in-memory training.

### Modified Capabilities

None (Hypnos consuming `phantasia.scenario` is specified in `hypnos-restructure`).

## Impact

- **Depends on:** `cognitive-cycle`/`syneidesis` (consumes broadcasts), `mnemos`
  (replay seeds), `hypnos` (training + scenario cue), **`mnemos-replay`** (replay
  cue; explicit dep). New dep: danijar/dreamerv3 vendored under `external/`; JAX
  (`jax[cpu]`) in the `[worldmodel]` extra.
- **GPU:** training during sleep uses the configured GPU (per the hardware split);
  `jax[cpu]` is the default — GPU is opt-in. Cold-start means early scenarios are
  low-quality until trajectories accumulate (documented limitation, paper §9).
- Ships disabled-by-default. Zero-persistence preserved: trajectories are derived
  workspace summaries, not raw sense data; in-memory-only training enforced.
