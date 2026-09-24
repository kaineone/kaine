## Why

Setting up KAINE today means a terminal: `python -m kaine.setup` asks a long run of yes/no prompts, then prints commands for the operator to run in the right order (Redis and Qdrant bootstraps, the model server, Nexus). The prompt sequence also includes a multi-gigabyte organ download that shows no progress. People who are not programmers, and especially those who are wary of the command line, stop there.

The wizard's step logic is already free of I/O (`kaine/setup/wizard.py` takes injected input and output functions), and Nexus already gives the project a local web stack. The missing piece is a setup experience in the browser that covers the same choices with the same safety gates.

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
- **A finish page that leads somewhere.** It shows a status light for each needed service and a "Start Nexus" button. Starting Nexus is not starting the entity. It also has a "Show sign-in token" control that reveals the generated token on click, inside the authenticated session.
- **Hard boundaries, enforced in code.** The browser setup cannot:
  - start or spawn the entity;
  - set `[research].enabled` or any operator-presence gate;
  - enable a non-loopback Nexus.

  Spawning stays a separate, explicit step with the welfare acknowledgement and the pre-boot checklist. An allowlist of config keys that setup may write is checked by a test.

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
  - any change to how the entity is spawned.
