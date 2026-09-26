## Why

The `nous.engine` seam lets a plugin replace Nous' active-inference engine outright. KAINE builds its own engine (`PymdpEngine`) from the operator's `[nous]` settings, which a plugin never sees, so a plugin that wants to keep that engine and add to it (observe its choices, or add a second opinion alongside it) cannot: it would have to rebuild the engine from duplicated settings, which drifts out of sync with the operator's configuration. The CL1 substrate plugin is the first case (a hybrid in which silicon keeps the beliefs and the tissue proposes a policy), but the need is general.

## What Changes

- **A wrapper seam for Nous' engine.** A plugin may declare `nous.engine_wrapper` and return, for Nous, `{"engine_wrapper": wrap}`, where `wrap(engine)` takes the engine KAINE built and returns an engine.
- **KAINE builds first, then wraps.** With a wrapper injected, `make_nous` validates the envelope and builds the default engine exactly as today, then calls the wrapper with it. The result must satisfy the `ActiveInferenceEngine` protocol (an `actions` property and a `step` method); otherwise boot stops with a `PluginError` naming the plugin.
- **One or the other.** A plugin (or two plugins) filling both `nous.engine` and `nous.engine_wrapper` stops the boot: a replacement and a wrapper cannot both apply.
- **Restarts.** Spot rebuilds Nous on a heavy restart; the wrapper is called again with the freshly built default engine, as injections already are.
- **No plugin, no change.** Without the seam, `make_nous` behaves exactly as today.

## Impact

- `kaine/plugins.py` (`INJECTABLE_SEAMS["nous"]` gains `engine_wrapper`; the both-filled check); `kaine/boot.py` (`make_nous`); `docs/plugins.md` (seam table); tests.
- Vendor-neutral: KAINE learns nothing about any substrate.
