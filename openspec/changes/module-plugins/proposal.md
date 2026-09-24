## Why

KAINE lets an operator choose the runtime behind a heavy organ through `[<module>].backend`, but only among backends that live in this repository. Research work that realises a module's forward model on a different substrate has no supported way to plug in. `boot.py` constructs every module itself (`make_chronos` calls `Chronos(bus, **kwargs)`), and Spot's heavy-restart path rebuilds modules through the same factories, so an out-of-tree package can only reach a module by patching private boot functions. That coupling breaks silently when boot changes, and a patched restart path could revert a module to its default model without anyone noticing.

Several modules already accept a replacement model through their constructor (`Chronos(network=)`, `Nous(engine=)`). Soma does not: it always builds its own `SubstrateForwardModel`. `BaseModule.attach_oscillator` accepts any oscillator, but boot always builds the default one.

## What Changes

- **Explicitly enabled plugins.** A new `[plugins]` section with `enabled = ["<name>", ...]`. KAINE discovers plugins through the `kaine.plugins` Python entry-point group but loads only the ones named there. An installed plugin that is not named is never imported. A named plugin that is missing, fails to import or fails to register stops the boot with a `ConfigurationError`, because booting on the default models after the operator asked for a substitution would be a pretend run.
- **A fixed set of injection seams.** A plugin may supply objects only for seams KAINE declares: `chronos.network`, `soma.forward_model`, `nous.engine` and the per-module oscillator. A plugin that returns any other key, or two plugins that claim the same seam, stop the boot. A plugin cannot enable or disable modules, change configuration or bypass any gate.
- **Soma gains `forward_model=`.** When it is `None` (the default) Soma builds `SubstrateForwardModel` exactly as today.
- **One construction path.** `build_registry` and Spot's `rebuild_module` construct modules through one shared function that applies the plugin injections, so a restarted module keeps its substituted model.
- **Substitutions are recorded.** Boot logs every substitution at WARNING, and the run manifest (`RunContext`) records each enabled plugin's name, version and the seams it filled, so evaluation can tell a substituted run from a default one.
- **Plugin configuration.** Each plugin reads its own `[plugins.<name>]` table. `validate_config_shape` checks that `plugins.enabled` is a list of strings.

With `[plugins]` absent or `enabled = []`, behaviour is identical to today and no entry point is read.

## Impact

- New capability `module-plugins`; modified capability `soma` (constructor seam).
- Code: new `kaine/plugins.py`; `kaine/boot.py` (shared construction, oscillator wiring); `kaine/cycle/__main__.py` (`rebuild_module` delegates to the shared function); `kaine/modules/soma/module.py`; `kaine/experiment/run_context.py`; `kaine/config.py`; import-linter contract that `kaine.modules` does not import `kaine.plugins`.
- No new dependencies (`importlib.metadata` is stdlib).
