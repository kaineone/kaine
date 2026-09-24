## Context

`kaine-cl1` has been developed downstream in a private repository and consumed `kaine` as a pinned dependency. Its code has no CL1 hardware path: it opens `cl.open()` in-process against the simulator, shares the 64 channels among converted modules through a broker, and injects models through the `chronos.network` and `soma.forward_model` seams.

Research on Cortical Labs' published material (2026-09-23) found:
- `cl-sdk` 1.0.0 (2026-06-11) is the only release, on PyPI and GitHub, licensed CC BY-NC 4.0.
- Its simulator generates non-learning control data that does not respond to stimulation.
- `cl.open()` takes no endpoint or credentials. A separate, closed `cl-api` package drives real hardware on the device.
- Cortical Cloud deploys user code (for example Jupyter notebooks) to run on the CL1 itself. No public documentation describes an external program driving a remote CL1.

## Decisions

**1. Separate distribution inside the repo.** Keeping `kaine-cl1` as its own package with its own `pyproject.toml` keeps core KAINE's dependency set and import graph unchanged, and makes installing it a deliberate act. Its version tracks KAINE's release and it depends on `kaine` at the same version.

**2. Point to `cl-sdk`, never install it.** No `kaine[cl1]` extra and no wizard install. The operator runs `pip install cl-sdk` themselves after reading the licence note. `kaine_cl1` imports `cl` lazily and checks for it in `seams()`, so an enabled plugin without `cl-sdk` fails at load time with the instructions, before any module is built.

**3. Data source is explicit and labelled.** The `reference_culture` source is a model written for this package: a seeded Poisson baseline plus evoked bursts whose size scales with stimulation amplitude. It lets the converted modules be exercised end to end on a responsive substrate. Its results say nothing about biology, and the docs and boot log say so.

**4. Cloud and hardware refused, with reasons.** `target` accepts only `"simulator"`. Supporting Cortical Cloud needs either a documented remote API or an on-device component that the operator deploys to their Cortical Cloud workspace. Neither can be designed from public information. Credential handling is deferred until then. When it comes, tokens will live outside `kaine.toml` (the secrets directory or the environment), never in logs or manifests.

**5. CI.** The package's pure tests (config, plugin validation, codec) run without `cl-sdk`. The simulator tests need `cl-sdk`, which CI would install from PyPI in a separate job. Using CC BY-NC software in the CI of a non-commercial open project is within the licence, but it is the operator's call. The job is marked optional until confirmed.

**6. Tests against KAINE, not a pin.** Inside the repo, the plugin's KAINE-boot tests run against the checked-out KAINE, so a core change that breaks the plugin fails in the same PR.

**7. Repo boundaries.**
- The plugin's files carry KAINE's own header (`LicenseRef-CAL-0.2` plus the copyright line), normalised with `scripts/apply_license_headers.py`; the plugin is CAL like the rest of the repo.
- The root pytest configuration collects only `tests/`, so `plugins/kaine-cl1/tests` is never collected by core CI and core tests never import `kaine_cl1` or `cl`.
- An import-linter contract forbids any `kaine` module from importing `kaine_cl1`; the plugin reaches core only through the `kaine.plugins` entry point.

**8. Naming outside `plugins/`.** Core code, `README.md` and architecture docs stay vendor-neutral ("an optional substrate plugin, see `plugins/kaine-cl1`"). The two operator-facing places whose job is to state the requirement name Cortical Labs, at the operator's direction: the wizard's optional step and `docs/cl1.md`.

**9. Sequencing.** The wizard and `docs/getting-started.md` edits are based on main after `first-run-service-fixes` (merged as kaine #180). The package move under `plugins/` does not touch those files and can go first.

**10. Config writes and the browser setup.** The wizard step writes the `[plugins]` block through `kaine.secrets_file` (`upsert_toml_field` / `read_toml_field`), which refuses layouts it cannot edit safely, rather than editing TOML by hand. If the browser-based setup (kaine #179) lands later, this step is re-expressed in its step model.

## Risks

- A simulated run could be mistaken for a biological one. Mitigated by the data-source label in the boot log and the docs. The seam entries in the manifest also mark the substitution.
- `cl-sdk` API drift. The plugin pins nothing but checks `cl.is_simulator()` and fails clearly on import errors. The tests exercise the SDK surface it uses.
- Blocking ticks. Accelerated time is still required until the non-blocking substrate lands.
