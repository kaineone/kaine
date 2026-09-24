## 1. Plugin loading

- [ ] 1.1 `kaine/plugins.py`: `KainePlugin` protocol, `PluginError`, `INJECTABLE_SEAMS`, `load_plugins(kaine_config)` reading `[plugins].enabled` and loading only named `kaine.plugins` entry points; reject duplicate entry-point names; validate declared seams and conflicts at load; fail closed.
- [ ] 1.2 `LoadedPlugins.injections_for(module)` checking returned keys against the declared seams; `oscillator_for(module, defaults)`; `manifest_entry()` using distribution metadata.
- [ ] 1.5 Load plugins in `cycle/__main__.py` before the manifest is written and pass them to `build_registry` and `rebuild_module`.
- [ ] 1.3 `validate_config_shape`: `plugins` must be a table and `plugins.enabled` a list of strings.
- [ ] 1.4 Import-linter contract: `kaine.modules` must not import `kaine.plugins`.

## 2. Seams and construction

- [x] 2.1 Soma: `forward_model: Optional[Any] = None` constructor parameter; default path unchanged.
- [x] 2.5 Chronos: size the forward-prediction head from the network's `units` when a network is injected; error if absent while forward prediction is on.
- [x] 2.6 `make_nous`: skip building `PymdpEngine` when `engine` is injected; keep envelope validation.
- [x] 2.2 `make_chronos`, `make_soma`, `make_nous` accept an `injections` mapping and pass it to the constructor.
- [x] 2.3 `boot.construct_module(...)` shared by `build_registry` and `cycle.__main__.rebuild_module`.
- [ ] 2.4 `_wire_oscillators` consults plugins for their declared `oscillator.<module>` seams before the snnTorch check; reject oscillator seams when the layer is disabled.

## 3. Recording

- [ ] 3.1 `RunContext.plugins` field populated at boot; WARNING log per filled seam.

## 4. Tests

- [ ] 4.1 Not enabled: entry point never loaded (fake entry point whose load would fail the test).
- [ ] 4.2 Enabled but missing, duplicate entry-point name, import error, and exception in `seams` or `injections`: `PluginError`.
- [ ] 4.3 Unknown seam, undeclared returned seam, and two-plugin conflict: `PluginError`, raised before construction where specified.
- [x] 4.9 Chronos with an injected network of a width other than `cfc_units` runs a forward-prediction tick without error.
- [ ] 4.10 Repeated `injections` calls across two Spot restarts each yield a working module.
- [ ] 4.4 Chronos, Soma and Nous receive injected objects; defaults unchanged with no plugins.
- [ ] 4.5 `rebuild_module` re-applies injections.
- [ ] 4.6 Oscillator override and conflict.
- [ ] 4.7 Manifest records name, version and seams; empty when no plugins.
- [ ] 4.8 Config shape: malformed `plugins.enabled` rejected.

## 5. Docs

- [ ] 5.1 `docs/plugins.md`: how to write and enable a plugin, the seam table, the fail-closed rule.
