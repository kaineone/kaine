## Context

Out-of-tree research packages need to replace the model inside a module while leaving the module body, its bus subscriptions and its event shapes untouched. The existing `runtime-backends` registry selects among in-tree backends by name and cannot load code from another package. Constructor injection already exists for Chronos and Nous and is how their tests substitute models.

## Decisions

**1. Entry points, gated by config.** Discovery uses `importlib.metadata.entry_points(group="kaine.plugins")`. Only entry points whose name appears in `[plugins].enabled` are loaded. Installing a package is therefore never enough to change a boot; the operator has to name it. Enumerating entry points reads package metadata only and imports nothing.

**2. Plugin interface.** The entry point resolves to a zero-argument callable returning an object with:

- `seams(config: dict) -> frozenset[str]`, the dotted seams the plugin will fill for this configuration (for example `{"chronos.network", "oscillator.chronos"}`);
- `injections(module: str, config: dict) -> dict[str, Any]`, returning constructor objects for that module's seams (empty when the plugin does not touch the module);
- optionally `make_oscillator(module: str, config: dict, defaults: dict) -> Any | None`.

`config` is the plugin's own `[plugins.<name>]` table. The interface is a `typing.Protocol` in `kaine/plugins.py`; plugins do not subclass anything.

Seams are declared up front so that validation, conflict detection and the run manifest all happen at load time, before any module is constructed and before the manifest is written (`cycle/__main__.py` writes the manifest before it calls `build_registry`). At construction time, `injections` and `make_oscillator` must return exactly the seams the plugin declared for enabled modules; returning an undeclared seam, or omitting a declared one for an enabled module, is an error.

`injections` and `make_oscillator` are called once per construction, which includes every Spot restart (`rewire_module` also re-creates every module's oscillator). A plugin that holds exclusive resources per module must accept repeated requests for the same module and hand the resource to the new object.

**3. Declared seams only.** `kaine/plugins.py` holds `INJECTABLE_SEAMS = {"chronos": {"network"}, "soma": {"forward_model"}, "nous": {"engine"}}`; oscillator seams are `oscillator.<module>` for any registered module. Adding a seam is a reviewed change to this table and to the module's constructor. Unknown seams and two plugins declaring the same seam are rejected at load time. Injections are requested only for modules that `[modules]` enables.

When `nous.engine` is filled, `make_nous` still validates the complexity envelope but does not build its own `PymdpEngine`.

When `chronos.network` is filled, Chronos sizes its forward-prediction head from the network's `units` attribute instead of `cfc_units` (the head reads the network's hidden state, so the two must agree). An injected network without `units` is a construction error when forward prediction is enabled.

**4. Fail closed.** Any failure while loading or asking a named plugin (missing entry point, more than one installed distribution exporting the same entry-point name, import error, exception in `seams` or `injections`) raises `PluginError` naming the plugin. `PluginError` is a `ValueError` defined in `kaine/plugins.py`; it is not `boot.ConfigurationError` because `boot` imports `kaine.plugins` and the reverse import would be a cycle. This differs from `resolve_backend`, which degrades: an operator who names a plugin has asked for a specific substitution, and a silent fallback would make the run look like something it is not.

**5. One construction function.** `boot.construct_module(name, bus, kaine_config, *, registry, entity_clock, intent_secret, injections)` replaces the duplicated dispatch in `build_registry` and `rebuild_module`. It takes the whole configuration and the registry rather than one section because the dispatch needs more than the module's own table: Topos and Audition receive the shared `[perception_feed]` (including the playlist clock that keeps video and audio in step), and Hypnos is built with its sibling modules. `rebuild_module` previously omitted the perception feed, so a restarted Topos or Audition lost it; the shared function removes that drift. It merges the plugin injections into the factory call; the factories for the seamed modules accept an `injections` mapping and pass its entries to the constructor. Spot therefore rebuilds a substituted module with a fresh injected object from the same plugin.

**6. Oscillators.** Plugin oscillators replace the default oscillator; they never switch the layer on. With `[oscillator].enabled = false`, no oscillator is attached and a plugin declaring an `oscillator.*` seam is rejected at load time. With the layer enabled, `_wire_oscillators` asks the plugin for each module whose `oscillator.<module>` seam it declared before checking for snnTorch, so a plugin oscillator does not need snnTorch; other modules keep the default path.

**7. Recording.** `RunContext.plugins` holds `{name: {"distribution": ..., "version": ..., "seams": ["chronos.network", ...]}}`, with the distribution name and version read from the entry point's package metadata rather than reported by the plugin. Boot logs one WARNING line per filled seam. The field is empty when no plugin is enabled, so manifests of default runs change only by an empty key.

## Non-goals

- The workspace-mediation ablation runner (`kaine/evaluation/benchmarks/workspace_mediation_ablation/runner.py`) constructs Chronos and Soma directly and does not go through boot. Running the ablation with plugin models is a separate change.

## Risks

- A plugin runs arbitrary code in the entity process once named. That is the same trust as any installed dependency; the config gate keeps it from happening by accident, and the manifest records it.
- A substituted model can behave very differently from the default. The seams carry no guarantee beyond the interface the module already calls; the plugin owns its model's correctness.
- State snapshots: a module's `state_dict` includes its model's state. A plugin model must implement `state_dict`/`load_state_dict`; restoring a snapshot taken with a different model is the plugin's responsibility to reject.
