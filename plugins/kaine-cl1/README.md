# kaine-cl1

An optional KAINE plugin that runs the forward models of selected modules on
Cortical Labs' CL1 biological neural compute. It runs on Cortical Labs'
simulator, and on a real CL1 only through a welfare gate. The operator guide, including requirements, licenses
and what is not supported yet, is [`docs/cl1.md`](../../docs/cl1.md).

## Quick start

```bash
pip install ./plugins/kaine-cl1   # from the KAINE repository root, in KAINE's environment
pip install cl-sdk                # Cortical Labs' SDK: CC BY-NC 4.0, installed by you
```

Then enable it in the KAINE configuration; the block to paste is in
[`config/kaine_cl1.example.toml`](config/kaine_cl1.example.toml).

## How it plugs in

KAINE discovers the `cl1` entry point in the `kaine.plugins` group and loads it
only when `[plugins].enabled` names it. The plugin declares the seams it fills
(`chronos.network`, `soma.forward_model`) and hands KAINE the objects for them.
Core KAINE never imports this package; an import-linter contract enforces that.

```
             ┌──────────── stock KAINE module (unchanged) ────────────┐
 workspace ─▶│ on_workspace / tick ─▶ [ forward model ] ─▶ publish(...) │
             └───────────────────────────────▲────┬───────────────────┘
                                             │    │
                   encode: input → stim ─────┘    └──▶ decode: spikes → hidden state
                                             │    ▲
                                  ┌──────────▼────┴──────────┐
                                  │  CL1 substrate (64 MEA)  │  one session, one broker,
                                  │  stim ▶        ◀ record  │  a channel territory per module
                                  └──────────────────────────┘
```

- **Substrate** (`src/kaine_cl1/substrate/`): one `cl.open()` session per
  process, a broker that leases disjoint channel territories and runs the closed
  loop, stimulation encoders and spike decoders, and the `reference_culture`
  synthetic data source.
- **Backends** (`src/kaine_cl1/backends/`): `WetwareTimingModel` for Chronos,
  `WetwareInteroceptiveModel` for Soma, `WetwareOscillator` for oscillatory
  binding, and `WetwarePolicyEngine`, which wraps Nous' engine with a policy
  proposal from the substrate.
- **Plugin** (`src/kaine_cl1/plugin.py`): validation, the operator messages, and
  the process-wide substrate. A module rebuilt by KAINE's supervisor reuses its
  channel territory.

## Layout

```
src/kaine_cl1/   the package
tests/           the plugin's tests (not collected by KAINE's own test run)
config/          the example [plugins.cl1] block
docs/            research notes: the CL API, the module conversion matrix,
                 biological welfare, and the foundation results
openspec/        the plan of record and its history, from when this package was
                 developed in a separate repository
```

## Tests

```bash
cd plugins/kaine-cl1
pip install -e '.[test]'
pytest
```

Tests that boot KAINE use the KAINE in this repository. Two comparisons with the
silicon models need torch and skip without it.

## License

The plugin is part of KAINE and licensed under the Cognitive Architecture License
(CAL) v0.2, like the rest of the repository. `cl-sdk` is Cortical Labs' software
under its own CC BY-NC 4.0 license; it is not included here. This project is not
affiliated with or endorsed by Cortical Labs.
