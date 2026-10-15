# First boot

This page covers the first supervised start of a KAINE entity. Read it if you have already installed KAINE and brought up the [supporting services](services.md), and you are sitting at the host that will run the cycle.

First boot is operator-supervised by default. The shipped `config/kaine.toml` turns every module off, and the cycle never starts on its own.

## Operator-supervised boot

### Read the security posture

Read the operator-responsibility items in [Security and privacy](../13-security-and-privacy.md) before proceeding.

The shipped `config/kaine.toml` has `[security.state_encryption] enabled = true`. If no encryption key is present, the cycle refuses to boot. The shipped `[dashboard].access` is `"open"`, so anyone who can reach the dashboard can view and control the entity without signing in; setting `access = "token"` restores the operator token and session sign-in. You can override the access mode at runtime with `KAINE_DASHBOARD_ACCESS`. Decide whether those defaults are appropriate for your deployment.

### Verify preconditions

```bash
export KAINE_FIRST_BOOT_OPERATOR_PRESENT=1
scripts/first-boot.sh
```

The script checks that Redis answers `PONG` on port 6479, Qdrant answers `/readyz`, every configured runtime URL is loopback, `config/secrets.toml` is gitignored (or does not yet exist), and the full pytest suite passes. Native services pass the same checks, so Docker is not required. If any check fails, the script exits non-zero and prints what is missing; fix it and re-run. The script does not start the cognitive cycle.

### Choose the module set

Module toggles belong in the gitignored `config/kaine.operator.toml`. The loader deep-merges that file over the shipped `config/kaine.toml` at boot. The shipped `config/kaine.toml` keeps every module `false` and a guard test enforces that, so leave it unedited.

If you have already run the first-run wizard (`python -m kaine.setup`), it wrote a full `[modules]` table to the operator file; those choices replace any profile defaults. The wizard offers the first configuration (the `first_configuration` module set) or the full entity (all fourteen cognitive modules, embodiment off), and recommends one from the host's hardware tier; see [Browser first-run wizard](README.md#browser-first-run-wizard).

If no profile is selected and `config/kaine.operator.toml` has no `[modules]` table, the loader applies the first-configuration `first_configuration` profile automatically (`kaine/config.py`). That profile is the effective default entity only in that case. To start the cycle with that choice explicit:

```bash
export KAINE_CYCLE_OPERATOR_PRESENT=1
python -m kaine.cycle
# equivalently:
KAINE_CYCLE_OPERATOR_PRESENT=1 KAINE_PROFILE=first_configuration python -m kaine.cycle
# or: KAINE_CYCLE_OPERATOR_PRESENT=1 python -m kaine.cycle --profile first_configuration
```

`first_configuration` turns on seven modules: the interoception, sequence (temporal prediction), vision (foveated), audition (raw sound as prediction error, speech-to-text off), affect (the affective core), sleep (fatigue-triggered sleep, voice alignment off), and language (the output-only language organ with a self-initiated voice) modules. It turns every other module off, including the effectors, vocal, self-model, episodic memory, planning, social cognition, world model, perceptual locus, embodiment and recorder modules. It also sets `[perception_feed]` to `mode = "seeded"` with `seed = 0`, `[vision].foveation = true`, `[sequence].forward_prediction = true`, `[audition].transcription_enabled = false`, `[audition].general_audition = true`, and `[action_selection].policy = "self_initiated_report"` with `drive_initiative = false` and `sig_expiry_s = 300.0`. Every other value (organ model, rates, encryption, speech-to-text model, world model backend and the rest) comes from the shipped `config/kaine.toml`.

For the full overlay, see `config/profiles/first_configuration.toml`. For how profile resolution works, see [Configuration](../appendix-a-configuration/README.md).

The equivalent hand-written `[modules]` block in `config/kaine.operator.toml`, if you prefer to compose it yourself:

```toml
[modules]
interoception       = true   # interoception
sequence    = true   # temporal awareness
vision      = true   # foveated vision; [vision] extra required
audition   = true   # raw sound as prediction error; [audio] extra required; transcription off
affect     = true   # affective core
language     = true   # output-only language organ; the model server must be serving
effectors     = false  # no effectors on first boot
vocal        = false  # TTS not part of the first-configuration voice path
self_model    = false  # held module
episodic_memory     = false  # held module
planning       = false  # held module
sleep     = true   # sleep analog; voice alignment stays off
social_cognition  = false  # held module
world_model  = false  # held module
perception = false  # held module (embodiment)
embodiment     = false  # held module (embodiment)
recorder       = false  # test infrastructure; off by default
```

The project keeps the held modules off until the planned test of the first configuration has a result, and the effectors module has no effector on first boot. An operator who wants to explore a held module can enable it individually (see [Day-to-day operation](../06-operation/README.md)), as a deliberate departure from the project default.

> Your per-install choices, including the profile, live in `config/kaine.operator.toml` and your launch environment, and they are never committed.

### Start Dashboard

In a dedicated terminal:

```bash
python -m kaine.dashboard
```

The dashboard starts on `http://127.0.0.1:8088/diagnostics/`. With the cycle not yet up, the page reports `cycle_status: not running`.

The shipped `[dashboard].access` is `"open"`, so no sign-in is needed. You can override the access mode with `KAINE_DASHBOARD_ACCESS` (`open` or `token`), make the dashboard read-only with `KAINE_DASHBOARD_READ_ONLY=1`, or add Tailscale hostnames with `KAINE_DASHBOARD_EXTRA_HOSTS`. To require an operator token or to serve the dashboard over your tailnet, see [opening the dashboard](../05-dashboard.md).

If no Redis password is configured yet, the dashboard exits with a message naming `bash scripts/redis-bootstrap.sh` instead of starting.

### Start the cycle

In a second terminal:

```bash
export KAINE_CYCLE_OPERATOR_PRESENT=1
python -m kaine.cycle
```

The entrypoint:

1. Loads `config/kaine.toml`.
2. Builds the event bus and audits Redis auth.
3. Builds the module registry from `[modules]` toggles.
4. Installs the state encryptor, and refuses to boot if encryption is enabled but no key is found.
5. Calls `module.initialize()` on every enabled module.
6. Writes `state/cycle/runtime.json` for the dashboard.
7. Begins ticking at `[cycle].processing_rate_hz` (default `10.0` Hz, 100 ms per tick).

In the operator-supervised path, the cycle refuses to start unless `KAINE_CYCLE_OPERATOR_PRESENT=1` is set. The preflight script `scripts/first-boot.sh` reads its own signal, `KAINE_FIRST_BOOT_OPERATOR_PRESENT`; the running cycle reads `KAINE_CYCLE_OPERATOR_PRESENT`. There are two other boot paths. An unsupervised research run starts only when its research gate verifies, among other conditions, that preservation, the welfare response, full logging and a preserve-and-revive round trip work on this install (see [For researchers](../14-for-researchers.md)). An opt-in unattended start must pass nine conditions at every boot and exits with code `6` when one fails.

If the organ returns no content, the cycle refuses boot and exits with code `9` unless `KAINE_ALLOW_MUTE_ORGAN=1` is set.

`Ctrl-C` shuts the cycle and every module down cleanly. Do not `kill -9` the process during a sleep phase; partial voice-alignment adapter writes are unsafe.

### Watch the first ticks

Open `http://127.0.0.1:8088/diagnostics/` and confirm:

- `cycle_status: running` and the cycle PID.
- `tick_index` advancing.
- `processing_rate_hz` and `experiential_rate_hz` matching `[cycle]`. In the code, `experiential_rate_hz` is the resting access rate (one broadcast every third processing tick, about 3.3 Hz); `experiential_rate_effective_hz` shows the rate on the latest tick, which rises after alerts and with arousal.
- The `modules` list matches what you enabled.

### Take a snapshot

After the first session, and before enabling a held module or the effectors module, consider taking a snapshot. Snapshots are created from inside the cycle process with `ForkManager.snapshot(registry, label=...)`; see [Forks and merges](../12-forks-and-merges.md) for the workflow.

## Enabling a module after first boot

See [Day-to-day operation](../06-operation/README.md). Each additional module is enabled by the operator in a supervised step.

## What KAINE does not do

- It calls no cloud service at runtime. All inference and cognitive processing is local, and model weights are downloaded once during setup.
- It does not record raw audio or video to disk. Live perception streams pass through processing in memory and are released. See [Security and privacy](../13-security-and-privacy.md#raw-perception-never-touches-disk).
- It does not start itself unless you opt in. Every launch needs the operator-present signal (`KAINE_CYCLE_OPERATOR_PRESENT=1`), a passing research gate in an unsupervised research run, or an opt-in unattended start that passes nine conditions at every boot, and the cycle refuses to boot if none holds. See [For researchers](../14-for-researchers.md).
- It does not act unless the effectors module is enabled and the operator has explicitly added shell or file-write whitelist entries.

## Roadmap and hardware portability

Longer-term directions, among them a distributed substrate, lighter hardware tiers and RISC-V, are covered in the [Roadmap](../appendix-d-roadmap.md) and [Hardware](../03-hardware/README.md) chapters. Some of the portability work is already built: `sherpa-onnx` speech for the audition and vocal modules, NumPy engines for the planning and world model modules, and containerized voice-alignment training.
