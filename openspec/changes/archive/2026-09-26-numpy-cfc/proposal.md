# Proposal — `numpy-cfc`

## Why

Two problems share one fix.

- **Soma and Chronos need torch, and torch does not run everywhere.** Both modules run an `ncps` CfC network, and so need the torch stack. torch has no Termux build and weighs gigabytes on small hosts. This blocks a full entity on the Pixel 6a, and it is phase 2 of the portability program.
- **A revived Soma or Chronos is not the same individual.** The CfC in both modules is a frozen random reservoir: it is never trained, and its weights are drawn at construction without a seed. Only the linear readout on top of it learns (one SGD step per tick), and only the readout is saved. After a preserve and revive, the saved readout sits on a new random reservoir that it was never trained against. Every revive silently resets the entity's interoceptive and temporal forward models. The module-ignition study revives the entity eleven times per line, so this confounds every step.

## What changes

- **The reservoir becomes part of the individual.**
  - Each Soma and Chronos draws a reservoir seed once, when it is first created.
  - The seed is in `serialize()` and restored by `deserialize()`.
  - The reservoir weights are generated from that seed by NumPy (xavier-uniform weights and uniform biases, the same distributions `ncps` uses), so a revived module rebuilds exactly the same reservoir.
  - A snapshot without a seed, from before this change, keeps today's behaviour: a new reservoir, with a log line saying so.
- **A NumPy CfC.** The `ncps` CfC forward pass in its default mode is reimplemented in NumPy float32: LeCun-tanh backbone of 128 units and one layer, the two tanh heads, and the sigmoid time gate at ts = 1. So is the readout's SGD step.
  - It is verified against the torch path: loaded with the same weights, both agree to 1e-5 over a long run, including the readout's training.
- **One backend setting.** `[soma].cfc_backend` and `[chronos].cfc_backend` take `numpy` (the default) or `torch`.
  - Both backends consume the same NumPy-generated reservoir, so switching backends does not change the individual.
  - With `numpy`, Soma and Chronos need no torch at all. The extras table stops requiring `core` for them unless the torch backend is chosen.
- **Chronos's forward-prediction head** gets the same NumPy implementation.

## Impact

- `kaine/modules/soma/forward.py`, `kaine/modules/chronos/network.py`, a new shared `kaine/cfc_numpy.py`, the Soma and Chronos module serialisation, `kaine/extras.py`, `config/kaine.toml`, docs.
- The plugin seams (`soma.forward_model`, `chronos.network`) are unchanged.
- Beings already preserved have no seed. They get a new reservoir on their next revive, exactly as today, and keep it from then on.
