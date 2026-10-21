## Why

The health snapshot's `backends` block reports runtime-backend load failures from `kaine.backend_state`, an in-process registry. The modules that record a failure load in the cycle process, and the dashboard runs in its own process (its own container in the compose deployment), so the dashboard's registry is always empty and the block always reads `ok`, even when the cycle fell back to a lighter backend or disabled a module. The block is also not shown on any page, only in `/diagnostics/health.json`.

## What Changes

- The cycle writes its registry's content-free failure records (module, backend, reason, fallback, time) into `state/cycle/runtime.json` as `backend_failures` on every runtime write.
- The dashboard's `backends` block reads them from there and adds any failure recorded in its own process. It reports where the answer comes from: `cycle` when the runtime file carries the list, `cycle_not_running` when there is no runtime file, and `not_reported` when the file lacks the key (a cycle from before this change). `ok` is true or false only when the cycle reported, or when the dashboard process itself recorded a failure; otherwise it is null.
- The health board shows the block: each failure with its fallback, "every selected backend loaded" when the cycle reports none, and the reason when it cannot tell.

## Capabilities

### Modified Capabilities

- `dashboard-observability`: backend load failures come from the cycle and are shown on the health board.

## Impact

- `kaine/cycle/__main__.py` (`_write_runtime_state`), `kaine/dashboard/health/prober.py` (`_backends_block`), `kaine/dashboard/health/blocks.py`, `kaine/dashboard/templates/_health_board.html`, `docs/05-dashboard.md`.
- Privacy: the records hold a module name, a backend name, a short reason, a fallback name and a time, as before.
