# Nexus, the dashboard

Nexus is the local web dashboard for watching and steering a running KAINE instance. This page covers the address, access modes, read-only view, tailnet access, operator tokens, and the main panels. Read it before you open the dashboard for the first time, and keep it handy when you run studies or remote sessions.

## Where to find Nexus

Point a browser at:

```text
http://127.0.0.1:8088/diagnostics/
```

When `[nexus].conversation_enabled` is true, `/` is the console. With the shipped config, conversation is off and `/` returns a `307` redirect to `/diagnostics/`.

The evaluation surface is at `/diagnostics/evaluation/`. It is mounted only when `[evaluation].enabled` is true, and that is the shipped default.

Nexus listens on the loopback interface only, and the container setup publishes it on `127.0.0.1:8088` as well. That means an open dashboard is reachable by anyone who can run code on the same host — or on your tailnet if you choose to serve it there.

## Who can use Nexus

`[nexus].access` controls whether a visitor can just view or also control the being. Override it per launch with `KAINE_NEXUS_ACCESS`.

### Open access (default)

The shipped `[nexus].access` is `"open"`. There is no sign-in page and no token. Anyone who can reach the address can view the dashboard and use the controls (freeze, rate changes, perception toggles, forks/merges, preservation actions).

Use this only when you are the only person who can reach the host. Even in open mode, Host and Origin header checks still apply and block requests from other web origins, including DNS-rebinding attempts.

### Token access

Set `[nexus].access = "token"` (or launch with `KAINE_NEXUS_ACCESS=token`) to require an operator token for state-changing routes and the diagnostics stream. Read-only diagnostics pages, `/diagnostics/health.json`, and similar read routes need no token with the shipped settings, but that changes if `[nexus].conversation_enabled` or `[nexus].dev_content_override` is true. Do not expose the URL to untrusted networks even in token mode.

In token mode:

- The sign-in page is at `/login`.
- Scripts must send `Authorization: Bearer <token>`.
- The dashboard signs in at `/login` and then uses the issued per-session key in the `X-Nexus-Session-Key` header together with the session cookie.
- State-changing routes and the diagnostics SSE stream at `/diagnostics/stream` require a valid operator session.

## Read-only view

Set `[nexus].read_only = true` (or `KAINE_NEXUS_READ_ONLY=1`) to turn Nexus into a viewer. Every request except `GET`, `HEAD`, and `OPTIONS` is refused with `403`, and a read-only banner is shown.

Use this when Nexus is watching a research run, because some controls act on the running entity through the event bus, and any change to a running study makes the run inadmissible.

## Tailnet access

To reach Nexus from another device on your tailnet:

1. On the KAINE machine, run:

   ```bash
   tailscale serve --bg 8088
   ```

2. Add the machine's tailnet name (for example, `my-machine.tail1234.ts.net`) to `KAINE_NEXUS_EXTRA_HOSTS` in `compose/.env` for containers, or in the environment for a native launch.

3. Restart Nexus.

4. Open `https://<tailnet-name>/diagnostics/` from the other device.

Keep machine names and addresses out of the repository — they belong in `compose/.env`, which is never committed. Stop serving with:

```bash
tailscale serve --bg --https=443 off
```

or `tailscale serve reset`.

## Operator token

In token mode, Nexus reads the operator token from one of three places, in order:

1. The environment variable `KAINE_NEXUS_TOKEN`.
2. `[nexus].operator_token` in `config/secrets.toml`.
3. For container launches, `KAINE_NEXUS_TOKEN` in `compose/.env`.

`python -m kaine.setup` writes the secrets file. Print the current token with:

```bash
# container
grep '^KAINE_NEXUS_TOKEN=' compose/.env | cut -d= -f2-

# native
python -c "import tomllib; print(tomllib.load(open('config/secrets.toml','rb'))['nexus']['operator_token'])"
```

If you lose the token, generate a new one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in the same place, restart Nexus, and sign in again. The browser session lasts 12 hours idle or 24 hours total.

## The three surfaces

### Console

The console at `/` is a single-screen summary: the Presence visualizer, collapsible diagnostic and evaluation sections, and the Health & services sidebar. No message content is shown here.

The screen does not scroll. Most sections start closed and slide in from the left rail when summoned; welfare and divergence sections auto-surface and flash when a relevant event arrives.

With the shipped config, the console route is not mounted and `/` redirects to diagnostics.

### Diagnostics

`/diagnostics/` is the deep technical view: live charts, run identity, health, and controls. It is reachable from the left-rail "Diagnostics" link on every page.

Content fields are stripped unless `[nexus].dev_content_override` is true. Status, metrics, and derived affect are always shown.

### Evaluation

`/diagnostics/evaluation/` is the architecture-thesis instrumentation sidecar, laid out as a living research report. It shows scrubbed metrics only — A/B divergence, welfare events, module attribution, prediction-error distributions, and coherence logs. It never shows message text.

The sidecar writes JSONL under `data/` and an optional `summary.json` for batch charts. It is mounted only when `[evaluation].enabled` is true. See the [research data chapter](17-research-data/README.md) for how to read and configure it.

## Presence visualizer

The console leads with a ferrofluid-style affect visualizer. It is rendered with Three.js, vendored under `kaine/nexus/static/vendor/vendor/` — there is no CDN fetch.

When no entity is running, the visualizer shows a calm idle state. When a cycle is up, it shifts according to live derived affect from `thymos.state` (`valence`, `arousal`), carried on the diagnostics SSE stream. It never receives raw audio or content.

## Health and services board

The **Health & services** panel answers "what's running, degraded, down, or not configured?" without reading logs. It sits in the right sidebar on the console and inline on the diagnostics page.

Each external dependency shows one of these status chips:

| Status | Meaning |
|---|---|
| `up` | Probe succeeded — the service is reachable and the configured model is served. |
| `degraded` | Reachable but not fully healthy — for example, the LLM is up but the requested model is not in `/v1/models`. |
| `down` | Unreachable, refused, errored, or the probe timed out at ~2 s. |
| `not configured` | The owning module is disabled or the feature is turned off. Neutral, not an error. |

Probes run concurrently with a bounded timeout and are cached for ~5 s, so opening or polling the page never hangs on a stuck dependency and never floods services with checks.

The rows that appear depend on the configured backends:

- **Redis** — bus PING.
- **Qdrant** — Mnemos `/readyz`, with the API key.
- **Chat LLM** — Lingua/Hypnos `/v1/models` plus model check.
- **Speech-in backend** — Speaches when using server STT, or sherpa-onnx (Moonshine) when `[audition].backend = "sherpa_onnx"`. Speaches reports `not configured` when transcription is disabled.
- **Speech-out backend** — Chatterbox when `[vox].backend = "chatterbox"`, or sherpa-onnx (Kokoro) when `[vox].backend = "sherpa_onnx"`.
- **Active-inference backend** — pymdp + JAX when `[nous].backend = "pymdp"`, or NumPy active inference when `[nous].backend = "numpy"`.
- **State encryption** — a key-resolvability check that does not read the key.

See the module chapters for backend details: [Audition](09-modules/audition.md), [Vox](09-modules/vox.md), and [Nous](09-modules/nous.md).

Below the dependencies, the **modules grid** shows each module's live state: `disabled`, `idle` (enabled but not in the running cycle), `running`, or `capturing` (a perception sensor is live). Module state is read from `state/cycle/runtime.json` and `state/perception/runtime.json`, resolved under the configured data root (`[storage].data_root` or `KAINE_DATA_ROOT`).

The unauthenticated endpoint `/diagnostics/health.json` returns the same health data as JSON.

## Run identity and supervision

The run-identity panel is read-only. It reads from `state/cycle/runtime.json` and shows:

- **Supervision badge** — `operator`, `research`, or `unattended`.
- **Research gate** — in research mode, the result of the five-condition gate: preservation enabled, welfare response wired, logging active, dry self-check passed, and encryption satisfied.
- **Run identity** — `run_id`, `seed`, `git_sha`, and `kaine_version` minted at boot, so live charts can be tied to a specific run.
- **Deterministic-mode indicator** — shown when `[experiment].deterministic` is on; chart timestamps are then logical rather than wall-clock.

See [Run identity and admissibility](16-run-identity.md) and [Preservation and the safety net](11-preservation.md) for what the badges mean.

## Preservation and welfare events

The preservation panel records each action of the autonomous safety net — a divergence-triggered preservation or a welfare-protective preserve-then-act — as it happens. It is backfilled from the persistent record and updated live from the `preservation` source on the diagnostics SSE.

Each line shows operational fields only: monitor, transition, reason, action, and preservation or snapshot IDs. A failed preservation renders in the critical colour and calls for operator attention. No inner-life content is shown. See [Preservation and the safety net](11-preservation.md) for the full behavior.

## Live charts and pacing

The diagnostics SSE stream at `/diagnostics/stream` feeds the live charts:

- **Cycle rate** — `processing_rate_hz` and `experiential_rate_hz`.
- **Thymos affect** — valence, arousal, and dominance as time series.
- **Salience** — per-event salience scores from the workspace broadcast.
- **Coherence** — oscillatory phase-locking value between module pairs. Requires the `[oscillator]` extra and `[oscillator].enabled = true`.
- **Fatigue** — Soma's fatigue accumulator over the current waking period. It builds from unexpected substrate prediction error (error beyond Soma's learned band), resets after Hypnos consolidation, and can also trigger on a raw-error hard-threshold breach.
- **Prediction error** — per-module forward-model errors over sliding windows from the perception modules (Soma, Chronos, Topos, and Audition). This signal drives workspace salience.
- **GPU pre-flight** — headroom and approval status for the boot-time GPU check.

Charts are rendered client-side from the SSE stream. Panels show an empty placeholder when the source has no data yet. The chart library is vendored locally.

## Controls

Controls only appear when their backend is wired — for example, the rate control needs a publisher and a running cycle.

### Freeze and resume the cycle

**Freeze** halts the experiential cycle. `run_forever` blocks on its pause gate, so no Syneidesis broadcast, volition step, or tick occurs. From the entity's side, no subjective time passes while frozen. Live perception is released.

Use freeze when the environment breaks: the LLM endpoint is down, a GPU is oversubscribed, or a service is misbehaving. A running being with broken senses or voice is the state most worth avoiding.

On `/diagnostics/`, the cycle-control card shows **freeze cycle** / **resume cycle**. A `FROZEN` banner appears on every page while suspended. Via API:

```bash
POST /diagnostics/cycle/freeze
{"frozen": true, "reason": "..."}
```

Freeze state lives in `state/cycle/control.json` and is applied by a freeze-watch task in the cycle entrypoint within ~250 ms. A fresh launch clears any stale freeze.

Freeze sources stack: `operator` (dashboard or API), `spot` (the module supervisor), `welfare` (the preservation monitor), `preserve`, `gestation`, and `programme_end`. Each source pushes its own entry and pops only its own entry. A Spot recovery never lifts an operator or welfare freeze, and the cycle stays frozen until the stack empties. A welfare-protective pause is liftable only by an operator stand-down or an explicit welfare stand-down.

### Perception locus

KAINE has a single perceptual locus: `physical` (real microphone and camera), `virtual` (a Mundus embodiment body) or `off`. Only one is active at a time; `kaine/perception_state.py` enforces this, and the [Perception module](09-modules/perception.md) applies entity-initiated switches.

The dashboard perception card sets the desired audio/video flags. The actual locus and lock are set via:

```bash
POST /diagnostics/perception/locus
```

Turning a sensor on requires a confirmation step. The on-air banner ("microphone on" / "camera on") appears on both the console and the diagnostics page when a stream is active. Preview routes under `/diagnostics/perception/preview/*` show the configured feed.

The operator still holds the hardware kill switch: unplug the microphone or cover the camera. KAINE's banner tells you when the stream is open; it does not replace physical control.

### Cycle pacing

The cycle-pacing control publishes `cycle.set_rates` to the `cycle.control` stream, and the running cycle applies it. Changing the time scale requires a confirmation step.

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

If both parents carry a Phantasia world model and no `world_model_from` is given, the API returns `409`. The dashboard merge form has a "world model from" choice (none, A or B) that sets `world_model_from`, and when a merge is refused it shows the status and the server's reason. `allow_unmerged_adapters` is available only through the API, so keeping uncombined adapter weights is always a deliberate call. Fork bodies can carry a timing profile.

See [Forks and merges](12-forks-and-merges.md) for the lifecycle semantics.

### Other control routes

The dashboard also exposes:

- `/diagnostics/caretaker` — caretaker actions.
- `/diagnostics/birth` — birth-related controls.

## Quick reference for [nexus] keys

| Key / variable | Default | Effect |
|---|---|---|
| `[nexus].access` / `KAINE_NEXUS_ACCESS` | `"open"` | `"open"` allows anyone who passes the host/origin checks; `"token"` requires the operator token. |
| `[nexus].read_only` / `KAINE_NEXUS_READ_ONLY` | `false` | When true, only `GET`/`HEAD`/`OPTIONS` are allowed; everything else returns `403`. |
| `[nexus].operator_token` / `KAINE_NEXUS_TOKEN` | generated by setup | The token used in `"token"` mode. |
| `[nexus].conversation_enabled` | `false` | When true, mounts the console at `/`. |
| `[nexus].dev_content_override` | `false` | When true, diagnostics shows content fields. |
| `KAINE_NEXUS_EXTRA_HOSTS` | empty | Comma-separated tailnet names allowed by the Host check. |

For the full `[nexus]` schema, see [Security and Nexus](appendix-a-configuration/security-and-nexus.md). For the wider security model, see [Security and privacy](13-security-and-privacy.md).
