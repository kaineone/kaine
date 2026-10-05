# The organ's runtime pieces leave kaine.setup

## Why

`kaine.setup` is install-time tooling. Three runtime paths still reached into it, which forced the "core runtime stays clear of edge features" import contract to allow indirect imports:
- the Hypnos organ window starts and stops the model server through `kaine.setup.model_server`;
- preboot checks the device map through `kaine.setup.device_map`;
- the Nexus health block checks the served alias through `kaine.setup.organ`.

The speech-verification change recorded these as a follow-up: moving them meant moving the model server, the organ module and the device map out of setup together.

## What changes

- **A new package, `kaine/organ_server/`:**
  - `lifecycle.py` holds all of `kaine/setup/model_server.py`: binary discovery, launch-command construction, supervision, health, and `cmd_start`/`cmd_status`/`cmd_stop`.
  - `served.py` holds the organ's identity and the served-model checks from `kaine/setup/organ.py`: the published repos, the GGUF file and directory, `served_gguf_path`, `OrganBackend`, `detect_organ_backend`, `ServedAliasResult` and `verify_served_alias`.
  - `device_map.py` holds all of `kaine/setup/device_map.py`.
- **`kaine/setup/organ.py` keeps the download half**: planning, running, the acquisition guide and revision state. It imports what it needs from `served`.
- **`kaine/setup/model_server.py` is a command-line entry.** `python -m kaine.setup.model_server start|status|stop` keeps working for the bootstrap script and the docs.
- **Callers import from the new modules.** That covers the organ window, Nexus health, preboot, the setup wizard, provisioning, a script and the tests.
- **Every definition moved verbatim.** An AST comparison with main shows the only differences are import lines inside four functions.
- **The edge contract is strict.** It now sets `allow_indirect_imports = false`, and every contract holds: no chain from the boot, cycle or workspace packages reaches `kaine.setup`. `kaine.organ_server` and `kaine.organ_probe` join the sidecar contract's list of top-level packages.

## Impact

- **Behaviour:** none. The code is unchanged; only its file moved.
- **Research:** none.
