# Nexus, the dashboard

Nexus is the local web dashboard for watching and steering a running KAINE instance. This page covers its address, access modes, read-only view, tailnet access, operator token and main panels. Read it before you open the dashboard for the first time.

## Where to find Nexus

Point a browser at:

```text
http://127.0.0.1:8088/diagnostics/
```

When `[nexus].conversation_enabled` is true, `/` is the console. With the shipped config, conversation is off and `/` returns a `307` redirect to `/diagnostics/`.

The evaluation surface is at `/diagnostics/evaluation/`. It is mounted only when `[evaluation].enabled` is true, which is the shipped default.

A native Nexus binds `127.0.0.1:8088` (`[nexus].host` and `port`). In containers it listens on all interfaces inside the container, and the port is published on `127.0.0.1:8088` only. Either way an open dashboard is reachable by anyone who can run code on the same host, and by your tailnet if you serve it there.

## Who can use Nexus

`[nexus].access` controls whether a visitor can just view or also control the being. Override it per launch with `KAINE_NEXUS_ACCESS`.

### Open access (default)

The shipped `[nexus].access` is `"open"`. There is no sign-in page and no token, and anyone who can reach the address can view the dashboard and use its controls (freeze, rate changes, perception toggles, forks and merges, preservation actions).

Use open access only when you are the only person who can reach the host. Host and Origin header checks still apply in open mode and block requests from other web origins, including DNS-rebinding attempts.

### Token access

Set `[nexus].access = "token"` (or launch with `KAINE_NEXUS_ACCESS=token`) to require an operator token for state-changing routes and the diagnostics stream. Read-only diagnostics pages, `/diagnostics/health.json` and similar read routes need no token with the shipped settings; that changes if `[nexus].conversation_enabled` or `[nexus].dev_content_override` is true. Keep the URL off untrusted networks even in token mode.

In token mode:

- The sign-in page is at `/login`.
- Scripts must send `Authorization: Bearer <token>`.
- The dashboard signs in at `/login` and then uses the issued per-session key in the `X-Nexus-Session-Key` header together with the session cookie.
- State-changing routes and the diagnostics SSE stream at `/diagnostics/stream` require a valid operator session.

## Read-only view

Set `[nexus].read_only = true` (or `KAINE_NEXUS_READ_ONLY=1`) to turn Nexus into a viewer. Every request except `GET`, `HEAD`, and `OPTIONS` is refused with `403`, and a read-only banner is shown.

Use it when Nexus is watching a research run, because some controls act on the running entity through the event bus and would change the run under study.

## Tailnet access

To reach Nexus from another device on your tailnet:

1. On the KAINE machine, run:

   ```bash
   tailscale serve --bg 8088
   ```

2. Allow the machine's tailnet name (for example, `my-machine.tail1234.ts.net`). For a native launch, set `KAINE_NEXUS_EXTRA_HOSTS` in the environment; for Compose, set it in `compose/.env`, which the `kaine-nexus` service passes through. `KAINE_NEXUS_EXTRA_HOSTS` adds the name to both the Host allow-list and the allowed origins. The Quadlet unit does not pass it, so on a Quadlet host follow [A dedicated headless host](07-deployment/headless-host.md), which adds the name to `[nexus].host_allowlist` and the origin to the unit.

3. Restart Nexus.

4. Open `https://<tailnet-name>/diagnostics/` from the other device.

Keep machine names and addresses out of the repository. They belong in `compose/.env` or your environment, which are never committed. Stop serving with:

```bash
tailscale serve --bg --https=443 off
```

or `tailscale serve reset`.

## Operator token

In token mode, Nexus reads the operator token from the environment variable `KAINE_NEXUS_TOKEN` first, then from `[nexus].operator_token` in `config/secrets.toml`. Compose passes `KAINE_NEXUS_TOKEN` from `compose/.env` into the container, and both container setups mount `config/secrets.toml` read-only. The token must be at least 32 characters, and Nexus refuses to start if a config file other than `config/secrets.toml` holds one.

`python -m kaine.setup` writes the secrets file. Print the current token with:

```bash
# Compose, when the token is set in compose/.env
grep '^KAINE_NEXUS_TOKEN=' compose/.env | cut -d= -f2-

# from the secrets file
python -c "import tomllib; print(tomllib.load(open('config/secrets.toml','rb'))['nexus']['operator_token'])"
```

If you lose the token, generate a new one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in the same place, restart Nexus, and sign in again. A browser session ends after `session_idle_minutes` (720, so 12 hours) without use or `session_max_hours` (24) in total.

## The three surfaces

### Console

The console at `/` is mounted only when `[nexus].conversation_enabled` is true; with the shipped config `/` redirects to diagnostics. It is a single screen that does not scroll, with the Presence visualizer, collapsible diagnostic and evaluation sections, and the Health and services sidebar, and it shows no message content. Most sections start closed and slide in from the left rail when you open them; the welfare and divergence sections open and flash when a relevant event arrives.

### Diagnostics

`/diagnostics/` is the deep technical view: live charts, run identity, health, and controls. It is reachable from the left-rail "Diagnostics" link on every page.

Content fields are stripped unless `[nexus].dev_content_override` is true. Status, metrics and derived affect are always shown.

### Evaluation

`/diagnostics/evaluation/` shows the evaluation sidecar's scrubbed metrics, among them A/B divergence, welfare events, module attribution, PLV coherence and per-source prediction error, and never shows message text. The prediction-error panel keeps a sliding window of errors from Soma, Chronos and Topos reports, Audition's transcription and emotion events, and Phantasia's world error.

The sidecar writes JSONL under `data/` and an optional `summary.json` for batch charts. See the [research data chapter](17-research-data/README.md) for how to read and configure it.

## Presence visualizer

The console leads with a ferrofluid-style affect visualizer, rendered with Three.js from `kaine/nexus/static/vendor/vendor/` with no CDN fetch. With no entity running it shows an idle state. When a cycle is up, it follows the derived affect in `thymos.state` (`valence`, `arousal`) carried on the diagnostics SSE stream, and it never receives raw audio or content.

## Health and services board

The Health and services panel shows which services are running, degraded, down or not configured, without reading logs. It sits in the right sidebar on the console and inline on the diagnostics page.

Each external dependency shows one of these status chips:

| Status | Meaning |
|---|---|
| `up` | The probe succeeded: the service is reachable and serves the configured model. |
| `degraded` | Reachable but not fully healthy, for example a model server whose `/v1/models` lacks the configured model. |
| `down` | Unreachable, refused or errored, or the probe timed out (2 s). |
| `not configured` | The owning module is disabled or the feature is off. This is neutral and is no error. |

Probes run concurrently with that timeout and their results are cached for 5 s, so the page never hangs on a stuck dependency or floods a service with checks.

The rows that appear depend on the configured backends:

| Row | Probe |
|---|---|
| Redis | A bus PING. |
| Qdrant | Mnemos's `/readyz`, with the API key. |
| Chat LLM | The model server's `/v1/models`, checked for the configured model. |
| Speech in | Speaches, or sherpa-onnx (Moonshine) when `[audition].backend = "sherpa_onnx"`. Speaches reports `not configured` while transcription is disabled. |
| Speech out | Chatterbox when `[vox].backend = "chatterbox"`, or sherpa-onnx (Kokoro) when `[vox].backend = "sherpa_onnx"`. |
| Active inference | pymdp and JAX when `[nous].backend = "pymdp"`, or NumPy when `[nous].backend = "numpy"`. |
| State encryption | Whether the key can be resolved, without reading it. |

See the module chapters for backend details: [Audition](09-modules/audition.md), [Vox](09-modules/vox.md), and [Nous](09-modules/nous.md).

Below the dependencies, the modules grid shows each module's live state: `disabled`, `idle` (enabled but not in the running cycle), `running`, or `capturing` (a perception sensor is live). Module state is read from `state/cycle/runtime.json` and `state/perception/runtime.json`, resolved under the configured data root (`[storage].data_root` or `KAINE_DATA_ROOT`).

The unauthenticated endpoint `/diagnostics/health.json` returns the same health data as JSON.

## Run identity and supervision

The run-identity panel is read-only. It reads from `state/cycle/runtime.json` and shows:

- the supervision mode: `operator`, `research` or `unattended`;
- in research mode, the result of the research gate's six conditions: preservation enabled, the welfare response wired, logging active, the dry preserve-and-revive self-check passed, encryption satisfied, and the individuation producer enabled (which needs Lingua);
- the run identity minted at boot (`run_id`, `seed`, `git_sha`, `kaine_version`), so live charts can be tied to a specific run;
- a deterministic-mode indicator when `[experiment].deterministic` is on, in which case chart timestamps are logical instead of wall-clock.

See [Run identity and admissibility](16-run-identity.md) and [Preservation](11-preservation.md) for what these mean.

## Preservation and welfare events

The preservation panel lists each action of the preservation monitors, a divergence-triggered preservation or a welfare-protective preservation followed by its action, as it happens. It is backfilled from the persistent record and updated live from the `preservation` source on the diagnostics SSE stream.

Each line shows operational fields only: monitor, transition, reason, action, and preservation or snapshot ids. A failed preservation is shown in the critical colour and needs the operator's attention. See [Preservation](11-preservation.md) for the full behaviour.

## Live charts and pacing

The diagnostics SSE stream at `/diagnostics/stream` feeds the live charts:

- Cycle rate: the processing rate and the access rate, from the `cycle.tick` and `cycle.rates` events on `cycle.out`. The second line (labelled "experiential Hz", after the config key `experiential_rate_hz`) is the access rate in effect on each tick.
- Thymos affect: valence, arousal and dominance as time series.
- Salience: the intensity of each module report, carried in the event's `salience` field. Cycle and workspace events are left out, because their values are operational or aggregate.
- Coherence: the phase-locking value of the modules competing in each broadcast (`metadata.coherence`). It needs the oscillator extra and `[oscillator].enabled = true`.
- Fatigue: Soma's fatigue accumulator over the current waking period. It builds from unexpected substrate prediction error (error beyond Soma's learned band) and resets when a Hypnos sleep completes.
- GPU pre-flight: headroom and approval status for the boot-time GPU check.

Charts are rendered in the browser from the SSE stream with a locally vendored chart library, and a panel shows a placeholder until its source has data. A read-only cycle pacing panel beside them shows whether the cycle holds its target rate, the time scale and any overrun.

## Controls

A control appears only when its backend is wired; the rate control, for example, needs a bus publisher and a running cycle.

### Freeze and resume the cycle

Freezing pauses the cycle: `run_forever` blocks on its pause gate, so no tick, broadcast or Volition step occurs, and no entity time passes for the being. An operator freeze also switches live perception off and restores it on resume.

Freeze when the environment breaks, for example when the model server is down, a GPU is oversubscribed or a service misbehaves, so the being does not run with broken senses or voice.

On `/diagnostics/`, the cycle-control card shows **freeze cycle** and **resume cycle** and which holders are freezing the cycle, and a `FROZEN` banner appears on every page while the cycle is suspended. Through the API:

```bash
POST /diagnostics/cycle/freeze
{"frozen": true, "reason": "..."}
```

Resume (`{"frozen": false}`) releases only your own freeze. A welfare, gestation or end-of-programme freeze stays until you override it by name, from the card's override button (a second click confirms) or the API:

```bash
POST /diagnostics/cycle/override
{"sources": ["welfare"], "confirm": "welfare"}
```

`confirm` must repeat the sources. Spot and preservation freezes release themselves and cannot be overridden. Each override is recorded, without content, in `state/cycle/override_audit.jsonl`.

Freeze state lives in `state/cycle/control.json`. A freeze-watch task in the cycle entrypoint polls it every 250 ms and applies it, and a fresh launch clears any stale freeze.

Freeze holders stack: `operator` (dashboard or API), `spot` (the module supervisor), `welfare` (the preservation monitor), `preserve`, `gestation` and `programme_end`. Each holder pushes its own entry and pops only its own, so a Spot recovery never lifts an operator or welfare freeze, and the cycle stays frozen until the stack is empty. A welfare-protective pause lifts only through an operator override that names it or an explicit welfare stand-down; resume does not lift it.

### Perception locus

KAINE has a single perceptual locus: `physical` (a real microphone and camera), `virtual` (a Mundus body) or `off`. Only one is active at a time. `kaine/perception_state.py` enforces this, and the [Perception module](09-modules/perception.md) applies switches the entity initiates.

The dashboard's perception card sets the desired audio and video flags. The locus itself and its lock are set through:

```bash
POST /diagnostics/perception/locus
```

Turning a sensor on asks for confirmation. While a stream is active, an on-air banner ("microphone on" or "camera on") appears on the console and the diagnostics page. The preview routes `/diagnostics/perception/preview/video` and `/diagnostics/perception/preview/audio` show the configured feed.

The banner tells you when a stream is open. To be certain a sensor is off, unplug the microphone or cover the camera.

### Cycle rates

The cycle rate control sets the processing rate and the resting access rate (`experiential_rate_hz`). After you confirm, it posts to `/diagnostics/cycle/rates`, Nexus publishes `cycle.set_rates` on the `cycle.control` stream, and the running cycle applies it. The change lasts until the next start. The time scale has no dashboard control. See [Day-to-day operation](06-operation/README.md#cycle-rates).

### Forks and merges

The dashboard can create a fork from a snapshot or merge two snapshots. The merge API accepts:

```bash
POST /diagnostics/merges
{
  "snapshot_a_id": "...",
  "snapshot_b_id": "...",
  "world_model_from": "a"|"b",
  "allow_unmerged_adapters": true|false
}
```

If both parents carry a Phantasia world model and no `world_model_from` is given, the API returns `409`. It also returns `409`, with the reason, when the adapter merge is refused: no real merger is available for two parents that carry adapters, or the merged adapter failed its capability or abliteration checks. Merges run in a worker thread, so a long check does not stall the dashboard. The dashboard's merge form has a "world model from" choice (none, A or B) that sets `world_model_from`, and when a merge is refused it shows the status and the server's reason. `allow_unmerged_adapters` is available only through the API, so keeping uncombined adapter weights is always a deliberate call. A fork request can also carry a timing profile (for example a `time_scale` for the fork).

See [Forks and merges](12-forks-and-merges.md) for the lifecycle semantics.

### Other control routes

The dashboard also exposes:

- `/diagnostics/caretaker`, the caretaker's status and acknowledgement (`/diagnostics/caretaker/ack`);
- `/diagnostics/birth`, the birth status and the operator's acknowledgement of a supervised birth (`/diagnostics/birth/ack`; see [Gestation](06-operation/gestation.md#supervised-birth)).

## Quick reference for [nexus] keys

| Key / variable | Default | Effect |
|---|---|---|
| `[nexus].host` / `KAINE_NEXUS_HOST` | `"127.0.0.1"` | The bind address. A non-loopback bind also needs `non_loopback_allowed`. |
| `[nexus].port` / `KAINE_NEXUS_PORT` | `8088` | The listening port. |
| `[nexus].non_loopback_allowed` / `KAINE_NEXUS_NON_LOOPBACK_ALLOWED` | `false` | Permits a non-loopback bind; the container setups set it because the container's port is published on loopback. |
| `[nexus].access` / `KAINE_NEXUS_ACCESS` | `"open"` | `"open"` allows anyone who passes the Host and Origin checks; `"token"` requires the operator token. |
| `[nexus].read_only` / `KAINE_NEXUS_READ_ONLY` | `false` | When true, only `GET`/`HEAD`/`OPTIONS` are allowed; everything else returns `403`. |
| `[nexus].operator_token` (in `config/secrets.toml`) / `KAINE_NEXUS_TOKEN` | generated by setup | The token used in `"token"` mode, at least 32 characters. |
| `[nexus].session_idle_minutes` | `720` | A browser session ends after this long without use. |
| `[nexus].session_max_hours` | `24` | A browser session's maximum length. |
| `[nexus].conversation_enabled` / `KAINE_NEXUS_CONVERSATION_ENABLED` | `false` | When true, mounts the console at `/`. |
| `[nexus].dev_content_override` | `false` | When true, diagnostics shows content fields. |
| `KAINE_NEXUS_EXTRA_HOSTS` | empty | Comma-separated host names (such as a tailnet name) added to the Host allow-list and the allowed origins. |

For the full `[nexus]` schema, see [Security and Nexus](appendix-a-configuration/security-and-nexus.md). For the wider security model, see [Security and privacy](13-security-and-privacy.md).
