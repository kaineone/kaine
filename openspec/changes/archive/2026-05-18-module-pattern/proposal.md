## Why

Every KAINE module follows the same structural contract — subscribe to
bus streams, process events according to specialization, publish to a
named output stream, read the workspace broadcast each cycle
(`docs/kaine-paper.md` §2.4). The contract is the architectural promise
that lets modules be added, removed, swapped, or shed without rewriting
the cycle or the workspace. If twelve modules each had ad-hoc lifecycles
and serialization formats, the fork-merge semantics from §4.3 would be
impossible.

This change exists separately from the modules themselves because the
base class, the registry, and the snapshot/restore protocol are
infrastructure all twelve modules consume — they need to be stable before
the first real module (Soma in Phase 2.1) ships.

## What Changes

- Introduce `kaine.modules.base.BaseModule` with the lifecycle hooks
  `initialize`, `process`, `publish`, `on_workspace`, `serialize`,
  `deserialize`, `shutdown`. All hooks are async to match the cycle's
  runner.
- Introduce `kaine.modules.registry.ModuleRegistry` tracking active
  modules by name, with health probes the cycle uses to decide whether
  to wait briefly for a module or skip it on a given tick.
- Define the `WorkspaceSnapshot` dataclass that Syneidesis emits and
  every module's `on_workspace` consumes.
- Ship `kaine.modules.echo.EchoModule` — a no-op module that publishes
  back whatever it was told to publish — as the integration test target
  for the whole Phase 1 stack. EchoModule is permanent test
  infrastructure, not a production module; it is excluded from the
  default module enable list in `config/kaine.toml`.
- Ship an integration test that wires bus + cycle + Syneidesis + Echo
  end-to-end and verifies a published event survives a full cognitive
  cycle and reaches `EchoModule.on_workspace`.

## Capabilities

### New Capabilities

- `module-pattern`: the base module class, the registry, the snapshot
  type, and EchoModule.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus`, `cognitive-cycle`, `syneidesis`. This is
  the last Phase 1 change; landing it closes Phase 1 and the milestone
  tag `v0.1-scaffolding` ships at the end.
- **Repo:** adds `kaine/modules/base.py`, `kaine/modules/registry.py`,
  `kaine/modules/echo.py`, `tests/test_module_base.py`,
  `tests/integration/test_phase_1_endtoend.py`.
- **No runtime impact** — modules are instantiable but no module state
  is allocated and the cycle is not started.
