## Context

Non-programmers should be able to install and configure KAINE without a terminal session beyond, at most, one command that the phase 2 launcher will later replace. The existing wizard already separates logic from I/O. Nexus already provides a FastAPI and Jinja stack, a stylesheet and a token model. The entity must never start as a side effect of setup.

## Goals / Non-Goals

Goals:
- Every choice available in the terminal wizard is available in the browser, with the same defaults and the same gates.
- Plain-language pages; long tasks with progress; failures that say what to do next.
- Setup is safe to re-run.

Non-Goals:
- Packaging, the launcher, Windows.
- Remote setup of another machine.
- Spawning the entity from setup.

## Decisions

### 1. A separate setup server, not a Nexus page
Nexus needs the event bus, and the event bus is one of the things setup creates. Nexus is also the entity's dashboard, with its own auth and privacy model. A small setup server (`kaine.setup.web`) runs before any service exists and exits when done. It reuses Nexus's stylesheet and fonts so the two look like one product.

Alternative considered: a "setup mode" inside Nexus. Rejected, because it would make Nexus start without a bus and would mix pre-install administration into the entity's dashboard.

### 2. One declarative step model
Each step is a `Step`: id, title, explanation, fields (type, default, choices, validator), `applies(config)` (whether the step is relevant) and `apply(config, answers)`. The terminal driver asks each field in order. The web driver renders each step as a form. `run_wizard` keeps its signature, so existing callers and tests keep working. A parity test runs both drivers on identical answers and compares the resulting configs.

Alternative considered: run the existing prompt loop in a thread and bridge `input_fn` to the browser. Rejected, because it would produce a chat-like sequence of prompts rather than readable pages, and it hides the structure the browser needs (defaults, choices, grouping).

### 3. Access control
- Bind 127.0.0.1 on a free port, and refuse any other bind.
- A 32-byte random launch token goes in the opened URL. It is exchanged once for an HttpOnly, SameSite=Strict session cookie and then invalidated.
- Every state-changing request checks the session, the Host header against the loopback names, and the Origin header.
- The server exits on finish or after 30 minutes idle.

The launch URL is also printed, for a browser that does not open automatically.

### 4. Long tasks as consented jobs
The organ download, extras install, dependency bootstraps and "Start Nexus" are jobs. A job starts only from an explicit POST made by a button click. It runs as a subprocess with an argument list, never a shell string built from input, and streams progress lines to the page over Server-Sent Events. The exact command is shown under "details". Output is kept in memory for the session and is not written to disk. It never contains secrets: the bootstraps never print them.

### 5. Merge on save
The step model knows which keys it owns. Saving loads the existing operator file, replaces only owned keys, and writes the result. Unowned keys, including hand edits, survive. The page shows the owned keys that change before the write. `tomlwriter` gains a merge that preserves unowned tables and keys; comments in the operator file are not preserved, and the page says so.

### 6. Boundaries enforced in code
A module-level allowlist in `kaine/setup/steps.py` lists every config key setup may write. `[research]`, the operator-presence environment gates, `[nexus].non_loopback_allowed` and any entity-start path are absent from it. A test fails if any step writes a key outside the allowlist, and another test proves the web app exposes no route that starts `kaine.cycle`.

### 7. Sign-in token hand-off
The finish page offers "Show sign-in token". It reveals the token from `config/secrets.toml` on click, within the authenticated setup session, and never puts it in a URL or a log.

Alternative considered: auto sign-in to Nexus. Deferred, because it would need a new Nexus login path, and that belongs to phase 2's launcher design.

## Risks / Trade-offs

- A browser-reachable server that can run install commands is a privileged surface. It is mitigated by loopback-only binding, the one-time token, Host and Origin checks, consent per job, argument-list subprocesses and the idle shutdown.
- A step-model refactor could change terminal wizard behaviour. It is mitigated by keeping `run_wizard`'s contract and existing tests, plus the parity test.
- Comments in `config/kaine.operator.toml` are lost on save. The page says so, and the file header already describes it as machine-written.

## Open Questions

- Platform order for phases 2 and 3: Linux desktop first, then macOS, is the working assumption.
