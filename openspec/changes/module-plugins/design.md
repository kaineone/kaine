## Context

Out-of-tree research packages need to replace the model inside a module while leaving the module body, its bus subscriptions and its event shapes untouched. The existing `runtime-backends` registry selects among in-tree backends by name and cannot load code from another package. Constructor injection already exists for Chronos and Nous and is how their tests substitute models.

## Decisions

**1. Entry points, gated by config.** Discovery uses `importlib.metadata.entry_points(group="kaine.plugins")`. Only entry points whose name appears in `[plugins].enabled` are loaded. Installing a package is therefore never enough to change a boot; the operator has to name it. Enumerating entry points reads package metadata only and imports nothing.

**2. Plugin interface.** The entry point resolves to a zero-argument callable returning an object with:

- `name: str` and `version: str`;
- `injections(module: str, config: dict) -> dict[str, Any]`, returning constructor objects for that module's declared seams (empty when the plugin does not touch the module);
- optionally `make_oscillator(module: str, config: dict, defaults: dict) -> Any | None`, where `None` means use the default oscillator.

`config` is the plugin's own `[plugins.<name>]` table. The interface is a `typing.Protocol` in `kaine/plugins.py`; plugins do not subclass anything.

**3. Declared seams only.** `kaine/plugins.py` holds `INJECTABLE_SEAMS = {"chronos": {"network"}, "soma": {"forward_model"}, "nous": {"engine"}}`. Adding a seam is a reviewed change to this table and to the module's constructor. Unknown keys, unknown modules and conflicts between plugins raise `ConfigurationError` at boot, before any module is constructed. Injections are requested only for modules that `[modules]` enables.

**4. Fail closed.** Any failure while loading or asking a named plugin (missing entry point, import error, exception in `injections`) raises `ConfigurationError` naming the plugin. This differs from `resolve_backend`, which degrades: an operator who names a plugin has asked for a specific substitution, and a silent fallback would make the run look like something it is not.

**5. One construction function.** `boot.construct_module(name, bus, section, *, entity_clock, intent_secret, plugins)` replaces the duplicated dispatch in `build_registry` and `rebuild_module`. It merges the plugin injections into the factory call; the factories for the seamed modules accept an `injections` mapping and pass its entries to the constructor. Spot therefore rebuilds a substituted module with a fresh injected object from the same plugin.

**6. Oscillators.** `_wire_oscillators` asks each enabled plugin's `make_oscillator` for a module before falling back to `kaine.oscillator.make_oscillator`. Two plugins returning an oscillator for the same module is a conflict.

**7. Recording.** `RunContext.plugins` holds `{name: {"version": ..., "seams": ["chronos.network", ...]}}`. Boot logs one WARNING line per filled seam. The field is empty when no plugin is enabled, so manifests of default runs change only by an empty key.

## Risks

- A plugin runs arbitrary code in the entity process once named. That is the same trust as any installed dependency; the config gate keeps it from happening by accident, and the manifest records it.
- A substituted model can behave very differently from the default. The seams carry no guarantee beyond the interface the module already calls; the plugin owns its model's correctness.
- State snapshots: a module's `state_dict` includes its model's state. A plugin model must implement `state_dict`/`load_state_dict`; restoring a snapshot taken with a different model is the plugin's responsibility to reject.
