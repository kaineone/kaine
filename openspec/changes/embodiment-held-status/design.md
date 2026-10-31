# Design: embodiment held status

## Context

The embodiment control plane was built in July 2026 (`body-agnostic-embodiment-adapters`, `intuitive-embodiment-control-surface`, both archived 2026-07-10) for a virtual body that was then to arrive through the Paracosmic connector. That connector is held pending a wire transport, the OpenSim stopgap was deferred under the operator's 2026-10-05 direction to put the mind before embodiment, and the motor learner, the driving loop and a physical body moved into the design-only `embodiment-motor-contingency`. What remains shipped is a control plane with a test body that answers every call with success.

The stub is valuable for unit tests: it pins the adapter protocol and the continuous-channel path. The problem is that it is also the default the config factory builds, and the module and the maturation gate cannot tell it from a body.

## Decisions

### D1. Choose held status now; the real body stays in `embodiment-motor-contingency`

Options:

1. Build a minimal real body now (a pan-tilt camera or a virtual body). This is what `embodiment-motor-contingency` designs, with its learner, driving loop and body-declared stages, and its start condition is the module-addition study's hardware stage. Building it now would put hardware and a motor loop in front of a study that does not use them, against the operator's mind-first direction.
2. Leave the code as is and rely on documentation. Rejected: the stub's success returns and the maturation gate's reachability check are behaviours, not wording, and the paper's "not built" is contradicted by an `embodied` stage reached with no body.
3. Make the code refuse to treat a reference body as a body, and derive every status surface from one check. Chosen. It is small, it changes nothing in any shipped configuration, and it turns itself off when `embodiment-motor-contingency` delivers a real adapter and loop.

### D2. `reference` is declared by the adapter

`EmbodimentCapabilities` gains `reference: bool`, default `False`, and the stub sets it to `True`. Declaring it on the descriptor keeps the decision with the adapter author, as `transitional` already is, and keeps the module body-agnostic: the module never checks a class name.

### D3. The config path refuses a reference body

The factory builds adapters from `[embodiment].adapter`. It refuses a reference adapter with a boot refusal ("embodiment is held: no body adapter is built; see embodiment-motor-contingency"), and the shipped value becomes `adapter = "none"`, which the factory treats the same way when the module is enabled. Unit tests keep constructing `EmbodimentModule(adapter=StubAdapter(), ...)` directly, which is the only way a reference body runs. There is no environment flag to let a reference body through, because such a flag would be the pretend path under another name.

Alternative considered: let the module start but log loudly and do nothing. Rejected: the developmental stage machine and the dashboard would still see an enabled embodiment module, and a log line is easy to miss in an unattended run.

### D4. Reachability and maturation never count a reference body

`probe_available()` returns `False` for a reference adapter. The maturation gate already treats an unreachable body as not ready (`gate_runner.py:204-216`, `644-650`), so no gate logic changes; a test pins the case. The efference copy's `forwarded` is true only when a non-reference adapter returned success.

### D5. The control surface cannot be enabled while nothing drives it

Config validation refuses `[embodiment.control_surface].enabled = true` while the motor driving loop does not exist. "Exists" is a code fact, a registered motor-seam driver, which `embodiment-motor-contingency` task 2.1 adds. Until then an enabled surface would be constructed and never stepped.

### D6. One derived status

`kaine.modules.embodiment.embodiment_built()` returns true only when the factory table holds a non-reference adapter and a motor-seam driver is registered. The wizard (no embodiment toggle while false), the dashboard health page (embodiment shown as "held: not built"), the study's `init` (an `--order` naming embodiment is refused while false) and a docs check read it. The docs check fails if `docs/09-modules/embodiment.md` claims a built body while the function is false.

## Risks

- A test that relied on the factory building the stub breaks. Those tests move to direct construction, which is what they test.
- An operator config with `[modules].embodiment = true` from earlier experiments now refuses to boot. The refusal message names this change's reason and the line to change.

## Migration and ordering

One pull request. It changes nothing the study runs (embodiment is off in the first configuration and not in the study's default order), but it does change the image. It lands before the study's launch image is built if it is ready in time; otherwise after the study, never as a mid-study image change. When `embodiment-motor-contingency` merges its adapter and loop, `embodiment_built()` turns true and its own tasks update the docs.

## Welfare and admissibility notes

With the module off nothing changes for any entity. The change removes a path by which an entity could have been staged as `embodied` with no body, a mismatch between the stage the entity's development records and what it can do. No welfare check is affected. Review: worker first pass and Claude's adversarial review; no second review needed, since no welfare, safety or persistence path changes.

## Implementation estimate (LLM-agent terms)

Size S. One pull request of about 200 to 350 lines including tests; 2 to 3 worker calls and one Claude review; half a day. No entity boots, no GPU.
