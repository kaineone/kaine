## Why

The paper's §4 table now says what is built: "body-agnostic control surface and curriculum with a reference stub body; the per-tick motor loop and a real body adapter are not built". The code does not yet behave as that sentence implies. An operator who turns the embodiment module on gets a body that pretends to work.

- The only adapter is `StubAdapter`, "a reference/test body, not a real one" (`kaine/modules/embodiment/adapters/stub.py:1-21`). The shipped config selects it (`config/kaine.toml:1623`, `adapter = "stub"`), and the factory builds it by default (`kaine/boot/factories/embodiment.py:23-29`).
- The stub reports success for everything: `probe()` returns `True`, `apply_action` and `apply_setpoints` record the call and return `True` (`stub.py:59-61`, `90-98`). The embodiment module then publishes an efference copy with `"forwarded": true` for a movement no body made (`kaine/modules/embodiment/module.py:319-339`).
- At maturation the gate runner asks whether a body is reachable (`kaine/lifecycle/gate_runner.py:204-216`) and activates it (`gate_runner.py:644-650`). With the module on and the operator approval set, the stub answers yes, so the entity's developmental stage becomes `embodied` with no body.
- The control surface can be enabled (`[embodiment.control_surface].enabled`), but "the per-tick driving loop is the cycle's motor seam ... not started by the control plane ... the surface is inert without it" (`module.py:96-101`). Nothing in `kaine/cycle` steps it.
- The module page opens "built and tested, and held" (`docs/09-modules/embodiment.md`), and the wizard offers embodiment as an ordinary module toggle (`kaine/setup/wizard_steps.py:308`).

This is the no-pretend-processes rule applied to a held module (audit B5, triage M08). The operator's direction is mind before embodiment (2026-10-05), and the real minimal body is already designed: `embodiment-motor-contingency` specifies the motor driving loop, the learner and a pan-tilt camera body, gated on the module-addition study's hardware stage. So this change does not build a body. It makes every surface say, and every code path behave as if, there is none.

## What Changes

- Adapters declare whether they are a reference body. The stub declares it is one.
- A reference body is never treated as a body outside unit tests: the config factory refuses to build one, so enabling the embodiment module with no real adapter is a named boot refusal; `probe_available()` is false for a reference body; the maturation gate never counts one as reachable.
- Enabling the control surface is refused at config validation while no driving loop exists, because an inert surface that reports itself enabled is a pretend process.
- An efference copy says `forwarded: true` only when a non-reference body accepted the command.
- One derived status, `embodiment_built`, true only when a non-reference adapter is registered and the motor loop exists. The wizard, the dashboard health page (`kaine/dashboard/health/`), the module-addition study's `init` and the docs read it. While it is false the wizard does not offer the module, the study refuses an `--order` that names embodiment, and the docs page states "held: no body adapter and no motor loop are built".
- `embodiment-motor-contingency` is the route to a real body; when its pan-tilt adapter and driving loop merge, `embodiment_built` turns true without editing this change's surfaces.

## Capabilities

### New Capabilities

- `embodiment-reference-body`: how a reference body is declared, refused and reported, and the derived build status.

### Modified Capabilities

None. The existing `embodiment-exposure` routing is unchanged.

## Impact

- Code: `kaine/modules/embodiment/adapter.py` (a `reference` field on the capabilities descriptor), `adapters/stub.py`, `module.py`, `kaine/boot/factories/embodiment.py`, `kaine/lifecycle/gate_runner.py`, config validation, `kaine/setup/wizard_steps.py`, `kaine/dashboard/health/blocks.py`, `kaine/research/ignition_study/__main__.py`.
- Config: `[embodiment].adapter` ships as `"none"`; a comment states the held status.
- Docs: `docs/09-modules/embodiment.md`, `docs/20-embodiment-adapters.md`, `docs/15-experiments/ignition-study.md`.
- Behaviour: none in any shipped configuration, since the module is off everywhere. With the module on, boot now refuses instead of running a no-op body.
