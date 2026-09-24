## 1. Step model

- [ ] 1.1 Add `kaine/setup/steps.py` with `Step` and `Field`, and express every current wizard step in it (orientation, welfare acknowledgement, hardware and devices, tier, accelerator mismatch, modules, model/voice/STT, trainer, metrics, encryption).
- [ ] 1.2 Add the owned-key allowlist and a test that no step writes outside it, including `[research]` (owned by the research harness) and any operator-presence gate.
- [ ] 1.3 Make `run_wizard` render the step model while keeping its signature and all existing wizard tests green.

## 2. Merge on save

- [ ] 2.1 Add a `tomlwriter` merge that replaces owned keys and preserves every other table and key.
- [ ] 2.2 Pre-fill from the existing operator file, and show the list of changes before writing.
- [ ] 2.3 Tests:
  - A hand-edited key survives a re-run.
  - An unchanged re-run writes identical content.

## 3. Setup server

- [ ] 3.1 Add `kaine/setup/web/` (FastAPI app and templates using the Nexus stylesheet), binding loopback only.
- [ ] 3.2 Launch token exchanged for a session cookie. Host and Origin checks. Idle and finish shutdown.
- [ ] 3.3 Step pages rendered from the step model, with server-side validation.
- [ ] 3.4 A parity test: the same answers through the web driver and the terminal driver give identical config.
- [ ] 3.5 `python -m kaine.setup --web` opens the browser and prints the URL.

## 4. Jobs

- [ ] 4.1 A job runner with argument-list subprocesses, a Server-Sent Events progress stream and plain status lines.
- [ ] 4.2 Jobs for the organ download (with progress), extras install, Redis and Qdrant bootstraps, and "Start Nexus".
- [ ] 4.3 Tests:
  - A job never starts without its POST.
  - Failures are reported and setup continues.
  - Only the spawn route can start `kaine.cycle`.

## 5. Finish page and docs

- [ ] 5.1 Service status lights, "Start Nexus", and "Show sign-in token".
- [ ] 5.2 Spawn action:
  - welfare acknowledgement recorded;
  - the full pre-boot check must pass;
  - separate confirmation;
  - start through the supervised path;
  - hand-off to Nexus.
- [ ] 5.3 Tests:
  - Each unmet gate refuses spawn.
  - A passing run starts exactly one cycle.
- [ ] 5.4 Accessibility pass: keyboard navigation, focus order, labels and contrast.
- [ ] 5.5 `docs/getting-started.md` leads with the browser setup. The terminal wizard is documented as an alternative.
- [ ] 5.6 `openspec validate browser-first-run --strict` passes.
