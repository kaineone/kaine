## Why

KAINE's thesis is that a mind is competition among predictive processors, each minimising prediction error. Cortical Labs' CL1 runs cultured cortical neurons on a 64-electrode array in a closed stimulate-and-record loop, and its cultures are described in the same free-energy terms. Running a module's forward model on neurons is therefore a direct test of the thesis on a second substrate. That work has lived in a private downstream package, `kaine-cl1`. It now boots inside stock KAINE through the `module-plugins` seams (kaine PR #172), with Chronos and Soma converted and tested on Cortical Labs' simulator.

This change brings that package into this repository so anyone can use it. It is off unless the operator installs it and names it, and it tells the operator plainly what it needs and what it cannot do yet.

## What Changes

- **A separate package in the repo.** `plugins/kaine-cl1/` is its own distribution (`kaine-cl1`) with its own `pyproject.toml`, exporting the `cl1` entry point in the `kaine.plugins` group. Installing KAINE does not install it. Core KAINE never imports it.
- **Cortical Labs' software is not shipped.** The package does not vendor or depend on `cl-sdk`. When the plugin is enabled and `cl` cannot be imported, the boot stops with a `PluginError` that tells the operator:
  - it needs Cortical Labs' `cl-sdk` (`pip install cl-sdk`), installed by the operator;
  - `cl-sdk` is licensed CC BY-NC 4.0, for non-commercial use only;
  - the simulator in `cl-sdk` is non-learning: Cortical Labs describes its data as control data that does not respond to stimulation and must not be relied upon for experiments;
  - real neurons need a paid Cortical Cloud account or a CL1 device.
- **Simulator only.** `target = "simulator"` is the only accepted target. `target = "cloud"` and `target = "hardware"` stop the boot and explain why. Cortical Cloud runs user code on the CL1 itself and publishes no API for an outside program to drive a remote CL1, so there is nothing yet for KAINE to connect to or authenticate against. The plugin also still requires accelerated simulator time, because a substrate tick blocks the cognitive loop until the non-blocking substrate lands.
- **An explicit data source.** Because the `cl-sdk` simulator's own data does not respond to stimulation, the plugin makes the choice explicit with `[plugins.cl1.substrate].data_source`:
  - `"reference_culture"` (default): the package's own synthetic culture model, whose evoked responses scale with stimulation amplitude. It is a model and is labelled as one;
  - `"sdk"`: `cl-sdk`'s own synthetic data, which ignores stimulation (a baseline control);
  - `"replay"`: a recording given by `replay_path`.
- **Every run is labelled.** The boot log states at WARNING that the substrate is simulated and names the data source. The plugin's manifest seams are unchanged, and the plugin adds the data source to its boot log line so a simulated run can never be mistaken for a biological one.
- **Setup wizard.** An optional wizard step, default no and skipped in defaults mode, explains the requirements above. If the operator says yes, it prints the install commands (`pip install ./plugins/kaine-cl1` and `pip install cl-sdk`, with the licence note) and writes a `[plugins]` block converting Chronos and Soma. The wizard never installs `cl-sdk` itself.
- **Docs.** `docs/cl1.md` covers what the plugin does, its requirements and licences, the data sources, the simulator-only status and why the cloud is not supported yet. `plugins/kaine-cl1/README.md` is the package page.
- **Contents moved.** From `kaineone/kaine-CL1`: `src/kaine_cl1/` (substrate session, broker and codec; Chronos and Soma backends; plugin; config), its tests, and its OpenSpec history for reference under `plugins/kaine-cl1/openspec/`. The `vendor/cl-sdk/` snapshot is not moved.

## Impact

- New: `plugins/kaine-cl1/`, `docs/cl1.md`, capability `cl1-substrate-plugin`.
- Modified: `kaine/setup/wizard.py` (the optional step); `DEPENDENCIES.md` and `THIRD_PARTY_LICENSES.md` (a note that `cl-sdk` is an operator-installed, non-bundled optional dependency and its licence); CI (see design); the import-linter contracts (core `kaine` must not import `kaine_cl1`).
- No change to core module behaviour. With the plugin not installed or not enabled, KAINE is unchanged.
