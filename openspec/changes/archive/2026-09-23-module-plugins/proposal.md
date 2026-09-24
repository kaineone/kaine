## Why

KAINE lets an operator choose the runtime behind a heavy organ through `[<module>].backend`, but only among backends that live in this repository. Research work that realises a module's forward model on a different substrate has no supported way to plug in. `boot.py` constructs every module itself (`make_chronos` calls `Chronos(bus, **kwargs)`), and Spot's heavy-restart path rebuilds modules through the same factories, so an out-of-tree package can only reach a module by patching private boot functions. That coupling breaks silently when boot changes, and a patched restart path could revert a module to its default model without anyone noticing.

Several modules already accept a replacement model through their constructor (`Chronos(network=)`, `Nous(engine=)`). Soma does not: it always builds its own `SubstrateForwardModel`. `BaseModule.attach_oscillator` accepts any oscillator, but boot always builds the default one.

## What Changes

- **Explicitly enabled plugins.** A new `[plugins]` section with `enabled = ["<name>", ...]`. KAINE discovers plugins through the `kaine.plugins` Python entry-point group but loads only the ones named there. An installed plugin that is not named is never imported. A named plugin that is missing, ambiguous, fails to import or fails to register stops the boot with a `PluginError`, because booting on the default models after the operator asked for a substitution would be a pretend run.
- **A fixed set of injection seams, declared up front.** A plugin states at load time which seams it fills, chosen from those KAINE declares: `chronos.network`, `soma.forward_model`, `nous.engine` and `oscillator.<module>`. An unknown seam, two plugins claiming one seam, or an object returned for an undeclared seam stops the boot. A plugin oscillator only replaces the default one; it cannot switch the oscillator layer on. A plugin cannot enable or disable modules, change configuration or bypass any gate.
- **Soma gains `forward_model=`.** When it is `None` (the default) Soma builds `SubstrateForwardModel` exactly as today.
- **Chronos sizes its prediction head from the network it uses.** Today the head is sized from `cfc_units` even when a network is injected, so an injected network of another width fails mid-cycle. With no injected network, `units` equals `cfc_units` and nothing changes.
- **One construction path.** `build_registry` and Spot's `rebuild_module` construct modules through one shared function that applies the plugin injections, so a restarted module keeps its substituted model.
- **Substitutions are recorded.** Boot logs every substitution at WARNING, and the run manifest (`RunContext`) records each enabled plugin's name, its distribution and version from package metadata, and its declared seams, so evaluation can tell a substituted run from a default one.
- **Plugin configuration.** Each plugin reads its own `[plugins.<name>]` table. `validate_config_shape` checks that `plugins.enabled` is a list of strings.

With `[plugins]` absent or `enabled = []`, behaviour is identical to today and no entry point is read.

## Impact

- New capability `module-plugins`; modified capabilities `soma` (constructor seam) and `chronos` (prediction-head sizing).
- Code: new `kaine/plugins.py`; `kaine/boot.py` (shared construction, oscillator wiring); `kaine/cycle/__main__.py` (`rebuild_module` delegates to the shared function); `kaine/modules/soma/module.py`; `kaine/modules/chronos/module.py`; `kaine/experiment/run_context.py`; `kaine/config.py`; import-linter contract that `kaine.modules` does not import `kaine.plugins`.
- The workspace-mediation ablation runner builds its modules directly and is out of scope.
- No new dependencies (`importlib.metadata` is stdlib).
