# Design — `operator-revive-and-preserve`

## Revive order

1. Parse `--revive <bundle>`. Read the bundle's members (`_read_bundle_members`, which decrypts when state encryption is on). A missing or unreadable bundle exits 7.
2. If the bundle carries `stage.json`, write it to the stage path BEFORE `_resolve_boot_stage` runs, so gestation, the womb hold and the gate all see the preserved stage. A bundle without a stage member (an older bundle) leaves the stage file untouched and logs that.
3. Build the registry and initialise the modules, as the research gate's self-check does. Initialise first, because Eidolon's `initialize()` reloads its disk file; a revive before it would be overwritten.
4. `await revive(bundle, registry)`. A `ReviveError` shuts the modules down and exits 7. A start that ends before the revive lands (a refused revive, a plugin error, any boot failure) restores the stage file to what it was before step 2, so the next start never pairs the bundle's stage with the previous individual's state.
5. Log the modules enabled now but not captured by the bundle as "new faculty, starting fresh". That is the study's add-a-module step.
6. Start the cycle, and record `revived_from` in `runtime.json` and the run context.

Modules start their background loops in `initialize()`, so a loop can run briefly on fresh state before the revive lands. This is the order the research gate already relies on. It is acceptable because the cognitive cycle, and so the workspace, has not started. It is documented at the site.

## Preserve request

- **Request file** `state/cycle/preserve_request.json`: `{request_id (32 hex), reason, stop, requested_at}`, written atomically by `python -m kaine.cycle.control preserve`.
- **Watcher.** A cycle-layer task polls every second. On a new `request_id`:
  1. `push_freeze(source="preserve")`, then wait for the freeze-watch loop to pause the cycle, up to 5 s;
  2. `preserve_live(registry, reason=..., label="operator", require_encryption=[preservation].require_encryption, ...)`;
  3. write `state/cycle/preserve_result.json`: `{request_id, ok, preservation_id, bundle, error}`;
  4. without `stop`, `pop_freeze(source="preserve")`; with `stop`, set the stop event and leave the freeze in place until exit.

  A request id is handled once; the result file records it.
- **Failure.** A failed preservation writes `ok: false` with the error and never stops the entity. The freeze is released, and the operator decides.
- **CLI.** `python -m kaine.cycle.control preserve` waits up to `--wait` seconds (default 120) for the matching result and exits 0 on success, 1 on failure, and 2 on timeout.

## Stage in the bundle

- `preserve_live` adds `stage.json` (the stage file's content) to the bundle's tar, encrypted with the rest.
- `revive()` ignores members it does not use; the stage member is applied by the entrypoint, not by `revive()`.
