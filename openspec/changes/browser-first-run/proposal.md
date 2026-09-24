## Why

Setting up KAINE today means a terminal: `python -m kaine.setup` asks a long run of yes/no prompts, then prints commands for the operator to run in the right order (Redis and Qdrant bootstraps, the model server, Nexus). The prompt sequence also includes a multi-gigabyte organ download that shows no progress. People who are not programmers, and especially those who are wary of the command line, stop there.

The wizard's step logic is already free of I/O (`kaine/setup/wizard.py` takes injected input and output functions), and Nexus already gives the project a local web stack. The missing piece is a setup experience in the browser that covers the same choices with the same safety gates.

The audience is people who run a full entity after the research phase. Research runs are configured and started by the automated research harness with its safety net, not through this setup.

This is phase 1 of three:
1. Browser first run (this change).
2. A single launcher, a desktop icon or one command, that starts the services in order and shows status lights.
3. A one-download installer.

It depends on `first-run-service-fixes`: re-runnable bootstraps, a generated sign-in token, and correct service probes.

## What Changes

- **`python -m kaine.setup --web`** starts a small local setup server and opens the browser on it. The same choices as the terminal wizard are presented as a sequence of plain-language pages, one per step, each with a short explanation and sensible defaults. Technical detail sits behind a "details" disclosure. The terminal wizard stays and remains fully supported.
- **One step model for both front ends.** The wizard's steps become declarative descriptions: title, explanation, fields, defaults, validation, and how each answer maps into the config. The terminal wizard and the browser both render these descriptions, so the two cannot drift. A parity test feeds the same answers to both and requires identical config.
- **Private to this computer.** The setup server:
  - binds only to 127.0.0.1;
  - requires a one-time launch token in the URL it opens, which becomes a strict session cookie on first use;
  - checks Host and Origin on every change;
  - shuts itself down when setup finishes or after a period of inactivity.
- **Long tasks run with consent and visible progress.** The organ download, dependency installs and the Redis and Qdrant bootstraps each start only when the operator clicks for that task. Each shows live progress and a plain status line, and offers the exact command under "details". A failure explains what happened and what to do next, and the rest of setup keeps working.
- **Re-running setup keeps what is there.** Pages are pre-filled from the existing `config/kaine.operator.toml`. Saving merges only the keys the wizard owns, so hand edits survive. The operator sees a summary of changes before anything is written. Today the file is overwritten wholesale.
- **A finish page that leads somewhere.** It shows a status light for each needed service, a "Start Nexus" button, and a "Show sign-in token" control that reveals the generated token on click, inside the authenticated session.
- **Spawning is a deliberate, gated action.** The finish page offers "Spawn the entity" only after:
  - the operator gives the CAL welfare acknowledgement, recorded at that moment;
  - the pre-boot check passes end to end: services up, organ serving the configured model, perception reaching the senses, welfare net armed, Nexus live.

  The page then shows what spawning means and asks for a separate confirmation. Setup never spawns as a side effect of any other step.
- **Research mode is not a setup choice.** `[research]` belongs to the automated research harness, so setup never writes it. An allowlist of the config keys that setup may write is checked by a test. It also excludes the operator-presence gates and `[nexus].non_loopback_allowed`.

## Impact

- Modified capability `first-run-wizard`: browser front end, a shared step model, merge-on-save, consented long tasks and boundaries.
- Code:
  - `kaine/setup/steps.py` (new: the step model and the existing steps expressed in it);
  - `kaine/setup/wizard.py` (the terminal driver renders the step model);
  - `kaine/setup/web/` (new: the FastAPI app, templates and a job runner with progress streaming);
  - `kaine/setup/__main__.py` (`--web`);
  - `kaine/setup/tomlwriter.py` (merge);
  - reuse of the Nexus stylesheet and fonts.
- No new dependencies. FastAPI, uvicorn and Jinja are already required by Nexus.
- Out of scope:
  - the launcher and the installer (phases 2 and 3);
  - Windows support;
  - changes to the cycle's own start gates. Spawning from the finish page goes through the existing supervised start path.
