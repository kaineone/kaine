## Why

kaine is gaining a general plugin mechanism (kaine change `module-plugins`, merged to kaine main as 97cfbae; implementation in progress). A plugin is a Python package that exports an entry point in the `kaine.plugins` group. kaine loads it only when `[plugins].enabled` names it, and it can supply replacement objects for a fixed set of declared seams (`chronos.network`, `soma.forward_model`, `nous.engine`, `oscillator.<module>`). That closes the gap this repo's foundation left open (task 5.1: live boot wiring). Once packaged as a plugin, `pip install kaine-cl1` plus a `[plugins.cl1]` table in the kaine config is enough to boot a kaine whose Chronos forward model runs on the CL1 substrate, with no separate boot script and no patching.

## What Changes

- **Entry point.** `pyproject.toml` exports `cl1 = "kaine_cl1.plugin:make_plugin"` in the `kaine.plugins` group.
- **Plugin object** (`kaine_cl1/plugin.py`) implementing kaine's plugin interface:
  - `seams(config)` returns the seams for every module whose backend is `"cl1"` in `[plugins.cl1.backends]`. Only modules with an implemented wetware backend are accepted; today that is Chronos (`chronos.network`). Setting any other module to `"cl1"` is an error that names the module and the change that will implement it.
  - `injections(module, config)` returns `{"network": WetwareTimingModel(...)}` for Chronos and `{}` for modules it does not convert.
  - No `make_oscillator` yet (oscillator-on-wetware is not implemented).
- **One substrate per process.** The plugin opens one `SubstrateSession` and one `SubstrateBroker` lazily on the first injection and closes the session at interpreter exit.
- **Restart-safe.** Spot restarts ask for a module's injection again. The plugin reuses the module's existing channel territory and discards stim still queued for it, instead of leasing a second territory.
- **Accelerated time required for now.** `run_cognitive_tick` blocks the caller for one cognitive tick of substrate time. On a real-time substrate that would stall kaine's event loop, so the plugin refuses to load unless `accelerated_time = true` until foundation task 3.3 (non-blocking guarantee) lands. Accelerated time is simulator-only, so this also keeps hardware out of reach through the plugin.
- **Configuration moves into the kaine config.** The overlay's settings are read from `[plugins.cl1]` (with `substrate`, `substrate.territories` and `backends` subtables) instead of a separate TOML file. `load_overlay(path)` stays for standalone use and shares the parser.

## Impact

- New capability `cl1-plugin`.
- Code: new `src/kaine_cl1/plugin.py`; `src/kaine_cl1/config.py` (parse from a mapping); `pyproject.toml`; `config/kaine_cl1.example.toml`; `README.md`; new `tests/test_plugin.py`.
- Closes foundation task 5.1 once the kaine side merges and the pin moves to it.
- Out of scope: the kaine-side end-to-end boot test (added when the pin moves to a kaine commit that contains the loader), Soma/Oscillator/Nous backends (their own changes), and the non-blocking substrate (foundation task 3.3).
