## Why

The operator's ruling (2026-10-01): Nexus "should just be unlocked locally, since it's only accessible on the same computer", and it may also be "available over my tailscale network, that was always part of the design". When asked about control actions, the operator chose **everything unlocked**: viewing and control both.

Today every privileged Nexus surface requires an operator token. The token lives in different places depending on the launch path (`compose/.env`, `config/secrets.toml`, or a file the docs name but nothing creates). An operator opening the dashboard meets a sign-in box asking for a value they were never told about. The bare address `http://127.0.0.1:8088/` also returns a 404 whenever the conversation console is off, which is every observed study.

The token was added (`nexus-privacy-hardening`) against two threats:
- **DNS rebinding and cross-site requests:** a web page reaching a loopback-bound instance. The Host allowlist and Origin checks defend against this independently of the token, and they stay.
- **Other processes on the host:** the operator accepts this for their own machine and tailnet.

## What Changes

- **`[nexus].access`:** `"open"` (shipped default) or `"token"`. Environment override: `KAINE_NEXUS_ACCESS`.
  - `"open"`: every surface works without a token or sign-in, viewing and control alike.
  - `"token"`: the existing behaviour, unchanged.
- **Open mode:**
  - `/login` redirects to the landing console.
  - The bearer-token and session dependency admits the request.
  - The Host allowlist and Origin/CSRF validation still apply to every request.
  - A one-time INFO log at startup says Nexus is open to anyone who can reach it, and lists the hosts it accepts.
  - Starting does not require a token. The non-loopback bind guard still requires `non_loopback_allowed`, the explicit statement that the deployment's own exposure (a loopback publish, a tailnet bind or `tailscale serve`) is the boundary.
- **Tailnet reachability:** `KAINE_NEXUS_EXTRA_HOSTS` (comma-separated; for example the machine's `*.ts.net` name or tailnet address) is added to the Host allowlist. Each name's `http://` and `https://` origins (with and without the published port) are added to the allowed origins. The recommended path is `tailscale serve --bg 8088`: the tailnet only, TLS included, proxying to the loopback port. Hostnames and addresses go only in operator-local files, never in the repository.
- **The root address** `/` redirects to the landing console when the conversation console is not mounted, instead of returning a 404.
- **Docs:** one "Opening Nexus" section, linked from the README, Getting Started, Operations and the container guide. It covers the address, the access modes, the token (where it lives for each launch path and how to print it) and the tailnet setup.

## Capabilities

### Modified Capabilities
- `nexus-dashboard`: the access mode, open by default; tailnet hosts; the root redirect.

## Impact

- **Code:** `kaine/nexus/config.py`, `kaine/nexus/auth.py`, `kaine/nexus/app.py`, `kaine/nexus/__main__.py`, `config/kaine.toml` (`[nexus].access`), `compose/kaine.yml` (passes `KAINE_NEXUS_ACCESS` and `KAINE_NEXUS_EXTRA_HOSTS`).
- **Security:** unchanged against websites (Host and Origin checks). Changed by operator decision for local processes and tailnet peers. `"token"` remains available for any exposure beyond those.
- **The running study:** Nexus only observes. Deploying this restarts the Nexus container, not the study.
