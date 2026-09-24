## 1. Plugin loading

- [ ] 1.1 `kaine/plugins.py`: `KainePlugin` protocol, `INJECTABLE_SEAMS`, `load_plugins(kaine_config)` reading `[plugins].enabled` and loading only named `kaine.plugins` entry points; fail closed with `ConfigurationError`.
- [ ] 1.2 `LoadedPlugins.injections_for(module, enabled_modules)` validating keys against `INJECTABLE_SEAMS` and rejecting conflicts; `oscillator_for(module, defaults)`; `manifest_entry()`.
- [ ] 1.3 `validate_config_shape`: `plugins` must be a table and `plugins.enabled` a list of strings.
- [ ] 1.4 Import-linter contract: `kaine.modules` must not import `kaine.plugins`.

## 2. Seams and construction

- [ ] 2.1 Soma: `forward_model: Optional[Any] = None` constructor parameter; default path unchanged.
- [ ] 2.2 `make_chronos`, `make_soma`, `make_nous` accept an `injections` mapping and pass it to the constructor.
- [ ] 2.3 `boot.construct_module(...)` shared by `build_registry` and `cycle.__main__.rebuild_module`.
- [ ] 2.4 `_wire_oscillators` consults plugins before the default oscillator.

## 3. Recording

- [ ] 3.1 `RunContext.plugins` field populated at boot; WARNING log per filled seam.

## 4. Tests

- [ ] 4.1 Not enabled: entry point never loaded (fake entry point whose load would fail the test).
- [ ] 4.2 Enabled but missing, import error, and exception in `injections`: `ConfigurationError`.
- [ ] 4.3 Undeclared seam and two-plugin conflict: `ConfigurationError`.
- [ ] 4.4 Chronos, Soma and Nous receive injected objects; defaults unchanged with no plugins.
- [ ] 4.5 `rebuild_module` re-applies injections.
- [ ] 4.6 Oscillator override and conflict.
- [ ] 4.7 Manifest records name, version and seams; empty when no plugins.
- [ ] 4.8 Config shape: malformed `plugins.enabled` rejected.

## 5. Docs

- [ ] 5.1 `docs/plugins.md`: how to write and enable a plugin, the seam table, the fail-closed rule.
