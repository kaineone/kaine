# Configuration reference

This page describes how KAINE loads and merges configuration, how to select a profile, how to keep secrets out of committed files, and how environment variables override values. Read it when you install KAINE, change a deployment, or enable modules.

## How configuration is loaded

[`config/kaine.toml`](../../config/kaine.toml) is the committed baseline and contains no secrets. Local overrides go in `config/kaine.operator.toml`. Optional named overlays live in [`config/profiles/*.toml`](../../config/profiles/). Deployment tiers are selected by `KAINE_TIER` or `[deployment].tier` and overlay hardware hints from the matching tier file. At runtime, the loader deep-merges the files in this order:

1. `config/kaine.toml`
2. `config/profiles/<name>.toml`, if `KAINE_PROFILE` selects a profile
3. The tier overlay, if `KAINE_TIER` or `[deployment].tier` selects one
4. `config/kaine.operator.toml`

The operator file wins over the tier, the tier wins over the profile, and the profile wins over the shipped file. `config/secrets.toml` is not merged into this stack; each subsystem reads its own secrets. Environment variables override the merged TOML where the code checks for them, with the exceptions noted below.

Select a profile with `KAINE_PROFILE=<name>` or `--profile <name>` on `python -m kaine.cycle`; the command-line flag wins over the environment variable. Running without a profile applies `config/profiles/thesis_test.toml` automatically. If the selected profile or tier file is missing, KAINE raises `ProfileError` instead of falling back silently.

## Module defaults

The committed `config/kaine.toml` ships with every module `enabled` toggle set to `false`. Enabling modules is a local edit that is never committed. The guard test `test_committed_config_ships_all_modules_disabled` in [`tests/test_boot_wiring.py`](../../tests/test_boot_wiring.py) checks this on every CI run.

With no profile selected, the loader applies the `thesis_test` profile automatically. That profile enables Soma, Chronos, Topos, Audition, Lingua, Thymos, and Hypnos; disables everything else (including Phantasia, Nous, Mnemos, Perception, and Mundus); sets `[perception_feed].mode` to `"seeded"` with `seed = 0`; sets `[topos].foveation = true`; sets `[chronos].forward_prediction = true`; sets `[audition].transcription_enabled = false` and `general_audition = true`; and sets `[volition].policy = "self_initiated_report"`, `drive_initiative = false`, and `sig_expiry_s = 300.0`. Every other value comes from the shipped config.

The operator file `config/kaine.operator.toml` merges last and wins. The first-run wizard (`python -m kaine.setup`) always writes a full `[modules]` table there, so on a wizard-configured install the wizard's module choices replace the profile's. The wizard offers two presets. The base thesis copies the `[modules]` table of `config/profiles/thesis_test.toml`. The full entity turns on all fourteen cognitive modules and leaves Perception and Mundus off. The wizard recommends the full entity when the host's hardware tier is 2 or higher and fits every module without residency swapping, and the base thesis otherwise; `--defaults` takes the recommendation, and a custom choice starts from it. Echo is always off. If Vox uses Chatterbox and no voice id is available, the wizard turns Vox off rather than write a configuration that cannot speak.

A profile that enables modules still does not birth an entity: the cognitive cycle refuses to boot unless the operator is present (`KAINE_CYCLE_OPERATOR_PRESENT=1`), a verified research safety net is configured, or an unattended gate passes. A profile only decides which modules construct and how they are configured. See [The modules](../09-modules/README.md), [First boot](../04-getting-started/first-boot.md), and [Preservation and the safety net](../11-preservation.md).

## Optional dependency extras

Several features need a Python extra installed on top of the base package:

| Extra flag | Command | Enables |
|---|---|---|
| `[audio]` | `pip install -e .[audio]` | Live microphone capture and decoding (`sounddevice`, `webrtcvad`, `funasr`, `librosa`, `av`) |
| `[speech-edge]` | `pip install -e .[speech-edge]` | Torch-free speech backends: sherpa-onnx (Moonshine STT, Kokoro TTS). Kokoro model: Apache-2.0 (model); GPL-3.0-or-later (espeak-ng-data and the espeak-ng engine built into sherpa-onnx) |
| `[vision]` | `pip install -e .[vision]` | Live camera capture and model helpers (`opencv-python-headless`, `transformers`, `Pillow`) |
| `[reasoning]` | `pip install -e .[reasoning]` | Active inference engine for Nous (`inferactively-pymdp`, `jax[cpu]`) — only required for the `pymdp` backend |
| `[worldmodel]` | `pip install -e .[worldmodel]` | DreamerV3 JAX engine for Phantasia (`jax[cpu]`, `chex`, `einops`); the NumPy engine needs no extra |
| `[oscillator]` | `pip install -e .[oscillator]` | Oscillatory binding layer (`snntorch`, `scipy`) |
| `[training]` | `pip install -e .[training]` | Voice alignment DPO/QLoRA training (`unsloth`, `trl`, `peft`, `datasets`) |

Additional grouped extras are available for specific subsystem and hardware paths: `[core]`, `[memory]`, `[memory-edge]`, `[nexus]`, `[nvidia]`, `[internvideo]`, `[internvideo-flash]`, `[perception]`, and `[full]`.

## Key validation

Most module factories validate their section against an allowlist and raise `ValueError` on unknown keys, so typos are caught before any module starts. Some loaders do not enforce allowlists and simply read the keys they need; extra keys pass silently in `[bus]`, `[redis]`, `[cycle]`, `[volition]`, `[experiment]`, `[perception_feed]` and its `.video`/`.audio`/`.screen` subsections, `[perception_preview]`, `[developmental_stage]` and `[developmental_stage.regulation_thresholds]`, `[ignition_log]`, `[research]`, `[research_submission]`, `[mundus.control_surface]`, `[logging]`, `[storage]`, `[hardware]`, and `[services]` (shape checks only), plus the perception constructor, the mundus constructor, `[hypnos.voice_alignment]`, `[remote_bridge]`, `[nexus]`, the `[evaluation*]` sections, the `[research_event_log*]` sections, `[transfer]`, and `[lifecycle]`. A typo in those sections will not be caught at boot.

## Profiles and deployment tiers

| Overlay | Purpose | Enables modules? |
|---|---|---|
| `thesis_test` | The base-thesis default. It enables Soma, Chronos, Topos, Audition, Lingua, Thymos, and Hypnos; disables everything else; sets `[perception_feed].mode = "seeded"` with `seed = 0`; sets `[topos].foveation = true`; sets `[chronos].forward_prediction = true`; sets `[audition].transcription_enabled = false` and `general_audition = true`; and sets `[volition].policy = "self_initiated_report"`, `drive_initiative = false`, and `sig_expiry_s = 300.0`. See [`config/profiles/thesis_test.toml`](../../config/profiles/thesis_test.toml). | Yes — the seven base-thesis modules. |
| `minimal_experiment` | A narrower, offline-experiment overlay: only Soma, Chronos, and Lingua; `[syneidesis].top_k = 2`, `[volition].drive_initiative = false`, `[lingua].temperature = 0.0`. See [`config/profiles/minimal_experiment.toml`](../../config/profiles/minimal_experiment.toml). | Yes — three modules. |
| `tier0` / `tier1` / `tier2` / `tier3` | Deployment-tier hardware hints, selected by `KAINE_TIER` or `[deployment].tier`. These overlays are inert by contract and never enable a module. Combine a tier with your own module choices in `config/kaine.operator.toml`. See [Choosing a deployment](../07-deployment/README.md). | No — hardware hints only. |

## Secrets file

`config/secrets.toml` is gitignored. Copy [`config/secrets.example.toml`](../../config/secrets.example.toml) to `config/secrets.toml` and fill in the real values. Set restrictive permissions:

```bash
chmod 600 config/secrets.toml
```

Real secret values are never printed in documentation or committed to the repository. `config/secrets.toml` is read by individual subsystems rather than being merged into the main config stack.

### Environment overrides

Environment variables override the merged TOML where the code reads them. They do not always win over every secret source:

- A `[lingua].api_key` set in config takes precedence over `KAINE_MODEL_SERVER_API_KEY`.
- The organ address defaults to `http://127.0.0.1:11434/v1` when `[lingua].chat_url` is unset. The organ default, the model-server key lookup and the free-disk floor are defined once, in `kaine/defaults.py`.
- Per-consumer `[mnemos|empatheia.qdrant].api_key` values take precedence over `KAINE_QDRANT_API_KEY` and any secrets-file value.
- `KAINE_STATE_KEY` is read from the environment or the keyring, not from `config/secrets.toml`.

| Env var | Overrides |
|---|---|
| `KAINE_PROFILE` | Select a profile overlay |
| `KAINE_TIER` | Select a deployment-tier overlay |
| `KAINE_DATA_ROOT` | Data root directory |
| `KAINE_CYCLE_UNATTENDED` | Unattended cycle gating |
| `KAINE_REDIS_URL` | Full `redis://` URL including auth |
| `KAINE_REDIS_PASSWORD` | Redis password only |
| `KAINE_REDIS_USERNAME` | Redis username for ACL setups |
| `KAINE_REDIS_MAXMEMORY` | Redis memory limit |
| `KAINE_QDRANT_API_KEY` | Qdrant API key |
| `KAINE_NEXUS_TOKEN` | Nexus operator token |
| `KAINE_NEXUS_HOST` | `[nexus].host` |
| `KAINE_NEXUS_PORT` | `[nexus].port` |
| `KAINE_NEXUS_CONVERSATION_ENABLED` | `[nexus].conversation_enabled` |
| `KAINE_NEXUS_NON_LOOPBACK_ALLOWED` | `[nexus].non_loopback_allowed` |
| `KAINE_NEXUS_ALLOWED_ORIGINS` | `[nexus].allowed_origins` |
| `KAINE_NEXUS_ACCESS` | `[nexus].access` (`open` or `token`) |
| `KAINE_NEXUS_READ_ONLY` | `[nexus].read_only` |
| `KAINE_NEXUS_EXTRA_HOSTS` | Extra tailnet or reverse-proxy host names |
| `KAINE_STATE_KEY` | State encryption key |
| `KAINE_MODEL_SERVER_API_KEY` | Model server API key, read when `[lingua].api_key` is unset |
| `KAINE_ORGAN_URL` | Organ address for the Hypnos trainer service, which runs without the config |
| `KAINE_MODELS_DIR` | Directory holding provisioned model weights |
| `KAINE_SMTP_PASSWORD` | SMTP password for email alerts |

### Redis secrets

| Key | Purpose |
|---|---|
| `password` | Redis authentication password. Generate with `openssl rand -hex 32`. Must match `compose/.env`. |
| `username` | Redis username (optional; only needed for ACL setups). |
| `url` | Full `redis://<user>:<password>@host:port/db` URL (optional alternative to individual fields). |

### Qdrant secrets

| Key | Purpose |
|---|---|
| `api_key` | Qdrant API key. Generate with `openssl rand -hex 32`. Must match `compose/.env`. Required by Mnemos and Empatheia when `backend = "qdrant"`. A per-consumer `[mnemos|empatheia.qdrant].api_key` takes precedence. |

### Nexus secrets

Put the Nexus operator token under `[nexus]` in `config/secrets.toml`, not in `config/kaine.toml` or `config/kaine.operator.toml`. If a non-empty `operator_token` appears in a non-secrets file, Nexus refuses to start. When a token is set, it must be at least 32 characters long. The shipped `[nexus].access` is `"open"`; set it to `"token"` (or set `KAINE_NEXUS_ACCESS=token`) to require the operator token. Full `[nexus]` network and token settings are on the [Security and Nexus](security-and-nexus.md) page.

### Caretaker tokens

Store caretaker authentication tokens under `[caretaker.tokens]` in `config/secrets.toml`.

## Section guide

The detailed reference is split across these pages:

- [Core, cycle and host](core.md) — `[cycle]`, `[experiment]`, `[syneidesis]`, `[volition]`, `[oscillator]`, `[modules]`, `[bus]`, `[spot]`, `[hardware]`, `[storage]`, `[services.<name>]`, `[preboot]`, `[gpu_preflight]`, `[remote_bridge]`, and `[logging]`.
- [Modules](modules.md) — per-module sections such as `[soma]`, `[chronos]`, `[topos]`, `[nous]`, `[mnemos]`, `[eidolon]`, `[thymos]`, `[praxis]`, `[lingua]`, `[audition]`, `[vox]`, `[empatheia]`, `[phantasia]`, `[mundus]`, `[perception]`, and `[embedding]`.
- [Perception feed and sleep](perception-and-sleep.md) — `[perception_feed]`, `[perception_feed.womb]`, `[perception_preview]`, `[hypnos]`, and `[hypnos.voice_alignment]`.
- [Lifecycle, evaluation and research](lifecycle-and-research.md) — `[evaluation]`, `[lifecycle]`, `[preservation]`, `[research]`, `[transfer]`, `[research_submission]`, `[research_event_log]`, and `[ignition_log]`.
- [Security and Nexus](security-and-nexus.md) — `[nexus]`, `[security.state_encryption]`, and related security settings.

For the structure and behaviour of individual modules, see the module pages under [The modules](../09-modules/README.md).
