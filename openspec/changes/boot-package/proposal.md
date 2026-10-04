# Split `kaine/boot.py` into a package behind a facade

## Why

The complexity audit of 2026-10-03 (W4) found `kaine/boot.py` at about 3,400 lines holding eight concerns: configuration errors, sixteen module factories, the perception stimulus feed and womb transition, the Hypnos voice-alignment resolvers, state-encryption install, registry construction, cross-module wiring and metrics. A change to one factory meant reading past all the others, and nothing stopped one factory from reaching into another.

## What changes

- `kaine/boot.py` becomes the package `kaine/boot/`. Every top-level definition moves verbatim:

  | Module | Contents |
  |---|---|
  | `errors.py` | `ConfigurationError`, `VoiceAlignmentConfigError`, `_require_keys`, `_pop` |
  | `common.py` | `ModuleFactory`, `shared_embedder`, `_check_injections`, `_effective_hot_swap_mode` |
  | `factories/<module>.py` | one `make_<module>` per file. `factories/hypnos.py` also holds the voice-alignment trainer resolvers, probe-set checks and organ-window runner. |
  | `perception_feed.py` | the stimulus feed and the womb-to-world transition |
  | `security.py` | `install_state_encryption` |
  | `registry.py` | `SIMPLE_FACTORIES`, `_CLOCKED_FACTORIES`, `plugin_injections`, `known_module_names`, `build_registry`, `construct_module`, `rewire_module` |
  | `wiring.py` | oscillators, the coherence scorer, salience factors, drive sources and the `_wire_*` helpers |
  | `metrics.py` | `_log_device_assignments`, `MetricsCollector` |

- `kaine/boot/__init__.py` re-exports every name the old module defined, so the files that import `kaine.boot` do not change.
- `_effective_hot_swap_mode` sits in `common.py` rather than with the Hypnos factory, because wiring and metrics use it too.
- A new import contract, "Module factories are independent", fails if one factory imports another.
- Each submodule logs under its own name (`kaine.boot.factories.soma` and so on). These are children of `kaine.boot`, so logging configured for `kaine.boot` still applies.
- Tests that patched `build_registry`'s collaborators through `kaine.boot` now patch them in `kaine.boot.registry`, where `build_registry` looks them up.
- The docs that pointed at `kaine/boot.py` point at the file that now holds each factory. The contributing guide describes adding a factory file.

Out of scope:
- Moving the `_wire_*` helpers out of `kaine/cycle/__main__.py`. They move with the boot-phase refactor (W5).
- W9 (one plugin object for the CL1 seam) needs no code change; the module-plugins work already meets it.
  - The loaded plugins are one `LoadedPlugins` object, and the registry holds it as `registry.plugins`.
  - Boot and the cycle reach it only through `injections_for`, `oscillator_for`, `cycle_observer` and `manifest_entry`.
  - The only free function left is `plugin_injections`, a four-line guard that returns `None` when no plugins are loaded or the module has no plugin seam.
  - Reshaping it further would touch the module-restart path (Chronos and Soma restart in place, Nous is rebuilt) for no gain.

## How the move was checked

A splitter in the operator's tooling moved each statement with the comments above it. Afterwards:
- every top-level definition's AST equals the one on main;
- each definition exists exactly once;
- every name is importable from `kaine.boot`, except the module logger.

## Impact

- **Behaviour:** none. The code is unchanged and only its file moved.
- **Research:** none. No study is running.
