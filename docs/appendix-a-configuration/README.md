# Configuration reference

This page describes how KAINE loads and merges configuration, how to select a profile, how to keep secrets out of committed files, and how environment variables override values. Read it when you install KAINE, change a deployment, or enable modules.

## How configuration is loaded

[`config/kaine.toml`](../../config/kaine.toml) is the committed baseline and contains no secrets. Local overrides go in `config/kaine.operator.toml`. Optional named overlays live in [`config/profiles/*.toml`](../../config/profiles/). Deployment tiers are selected by `KAINE_TIER` or `[deployment].tier` and overlay hardware hints from the matching tier file. Study configurations live in [`config/studies/*.toml`](../../config/studies/) and are selected by `KAINE_STUDY`. At runtime, the loader deep-merges the files in this order:

1. `config/kaine.toml`
2. `config/profiles/<name>.toml`, if `KAINE_PROFILE` selects a profile
3. The tier overlay, if `KAINE_TIER` or `[deployment].tier` selects one
4. `config/kaine.operator.toml`
5. `config/studies/<name>.toml`, if `KAINE_STUDY` selects a study

A study configuration wins over everything, so a study run's settings cannot be changed by the operator file. The operator file wins over the tier, the tier wins over the profile, and the profile wins over the shipped file. `config/secrets.toml` is not merged into this stack; each subsystem reads its own secrets. Environment variables override the merged TOML where the code checks for them, with the exceptions noted below.

Select a profile with `KAINE_PROFILE=<name>` or `--profile <name>` on `python -m kaine.cycle`; the command-line flag wins over the environment variable. Running without a profile applies `config/profiles/first_configuration.toml` automatically. If the selected profile, tier or study file is missing, KAINE raises `ProfileError` instead of falling back silently. A study file may set only the `[language]`, `[workspace]`, `[experiment]`, `[individuation]`, `[planned_test]` and `[positive_control]` tables and the single key `[audition].tone_rule`; any other table or `[audition]` key, `[modules]` included, raises `ProfileError`. The run manifest records the study's name in `study`.

Not every entry point uses the full stack. The cycle, the pre-boot check, `python -m kaine.lifecycle`, `python -m kaine.research` and the setup web app's cycle launches load the configuration through the runtime loader, with profile, tier and study. The dashboard, setup provisioning (`python -m kaine.setup`), the organ server's launcher (`kaine.organ_server.lifecycle`) and the control command (`python -m kaine.cycle.control`) load only `config/kaine.toml` and the operator file, with no profile, tier or study, so they do not see a study's `[workspace].arm` or its `[language].temperature`. Lifecycle and revive commands (`python -m kaine.lifecycle ...`, `python -m kaine.cycle --revive ...`) read `KAINE_STUDY` from the environment, so run them with the same `KAINE_STUDY` as the run they act on; otherwise they act under a different configuration from the one the run used.

## Module defaults

The committed `config/kaine.toml` ships with every module `enabled` toggle set to `false`. Enabling modules is a local edit that is never committed. The guard test `test_committed_config_ships_all_modules_disabled` in [`tests/test_boot_wiring.py`](../../tests/test_boot_wiring.py) checks this on every CI run.

With no profile selected, the loader applies the `first_configuration` profile automatically. That profile enables the interoception, sequence, vision, audition, language, affect, and sleep modules; disables everything else (including the world model, planning, episodic memory, perceptual locus and embodiment modules); sets `[perception_feed].mode` to `"seeded"` with `seed = 0`; sets `[vision].foveation = true`; sets `[sequence].forward_prediction = true`; sets `[audition].transcription_enabled = false` and `general_audition = true`; and sets `[action_selection].policy = "self_initiated_report"`, `drive_initiative = false`, and `sig_expiry_s = 300.0`. Every other value comes from the shipped config.

The operator file `config/kaine.operator.toml` merges last and wins. The first-run wizard (`python -m kaine.setup`) always writes a full `[modules]` table there, so on a wizard-configured install the wizard's module choices replace the profile's. The wizard offers two presets. The first configuration copies the `[modules]` table of `config/profiles/first_configuration.toml`. The full entity turns on all fourteen cognitive modules and leaves the perceptual locus and embodiment modules off. The wizard recommends the full entity when the host's hardware tier is 2 or higher and fits every module without residency swapping, and the first configuration otherwise; `--defaults` takes the recommendation, and a custom choice starts from it. The recorder module is always off. If the vocal module uses Chatterbox and no voice id is available, the wizard turns the vocal module off rather than write a configuration that cannot speak.

A profile that enables modules still does not mature an entity: the cognitive cycle refuses to boot unless the operator is present (`KAINE_CYCLE_OPERATOR_PRESENT=1`), a verified research safety net is configured, or an unattended gate passes. A profile only decides which modules construct and how they are configured. See [The modules](../09-modules/README.md), [First boot](../04-getting-started/first-boot.md), and [Preservation and the safety net](../11-preservation.md).

## Optional dependency extras

Several features need a Python extra installed on top of the base package:

| Extra flag | Command | Enables |
|---|---|---|
| `[audio]` | `pip install -e .[audio]` | Live microphone capture and decoding (`sounddevice`, `webrtcvad`, `funasr`, `librosa`, `av`) |
| `[speech-edge]` | `pip install -e .[speech-edge]` | Torch-free speech backends: sherpa-onnx (Moonshine STT, Kokoro TTS). Kokoro model: Apache-2.0 (model); GPL-3.0-or-later (espeak-ng-data and the espeak-ng engine built into sherpa-onnx) |
| `[vision]` | `pip install -e .[vision]` | Live camera capture and model helpers (`opencv-python-headless`, `transformers`, `Pillow`) |
| `[reasoning]` | `pip install -e .[reasoning]` | Active inference engine for the planning module (`inferactively-pymdp`, `jax[cpu]`); needed only for the `pymdp` backend |
| `[worldmodel]` | `pip install -e .[worldmodel]` | DreamerV3 JAX engine for the world model module (`jax[cpu]`, `chex`, `einops`); the NumPy engine needs no extra |
| `[oscillator]` | `pip install -e .[oscillator]` | Oscillatory binding layer (`snntorch`, `scipy`) |
| `[training]` | `pip install -e .[training]` | Voice alignment DPO/QLoRA training (`unsloth`, `trl`, `peft`, `datasets`) |

Additional grouped extras are available for specific subsystem and hardware paths: `[core]`, `[memory]`, `[memory-edge]`, `[dashboard]`, `[nvidia]`, `[internvideo]`, `[internvideo-flash]`, `[perception]`, and `[full]`.

## Key validation

Most module factories validate their section against an allowlist and raise `ValueError` on unknown keys, so typos are caught before any module starts. Some loaders do not enforce allowlists and simply read the keys they need; extra keys pass silently in `[bus]`, `[redis]`, `[cycle]`, `[action_selection]`, `[experiment]`, `[perception_feed]` and its `.video`/`.audio`/`.screen` subsections, `[perception_preview]`, `[developmental_stage]` and `[developmental_stage.regulation_thresholds]`, `[ignition_log]`, `[research]`, `[research_submission]`, `[embodiment.control_surface]`, `[logging]`, `[storage]`, `[hardware]`, and `[services]` (shape checks only), plus the perception constructor, the embodiment constructor, `[sleep.voice_alignment]`, `[remote_bridge]`, `[dashboard]`, the `[evaluation*]` sections, the `[research_event_log*]` sections, `[transfer]`, `[lifecycle]` and `[security.state_encryption]`. Nested tables read key by key inside a checked section, such as `[episodic_memory.qdrant]`, `[episodic_memory.replay]`, `[social_cognition.qdrant]`, `[effectors.shell_whitelist.<name>]` and `[world_model.world_model]`, also let an unknown key pass. A typo in those sections will not be caught at boot.

## Profiles and deployment tiers

| Overlay | Purpose | Enables modules? |
|---|---|---|
| `first_configuration` | The first-configuration default. It enables the interoception, sequence, vision, audition, language, affect, and sleep modules; disables everything else; sets `[perception_feed].mode = "seeded"` with `seed = 0`; sets `[vision].foveation = true`; sets `[sequence].forward_prediction = true`; sets `[audition].transcription_enabled = false` and `general_audition = true`; and sets `[action_selection].policy = "self_initiated_report"`, `drive_initiative = false`, and `sig_expiry_s = 300.0`. See [`config/profiles/first_configuration.toml`](../../config/profiles/first_configuration.toml). | Yes, the seven first-configuration modules. |
| `workspace_mediation_competitive` / `workspace_mediation_matched` / `workspace_mediation_pooled` | Study configurations in `config/studies/`, selected by `KAINE_STUDY`, one per arm of the planned workspace-mediation test. Each sets `[language].temperature = 0.0` (greedy decoding), its `[workspace].arm` and `[planned_test].role = "test"` with the settings record, and is applied after the operator file. The boot refuses them without a valid settings record. | No, settings only. |
| `workspace_mediation_preliminary`, `workspace_mediation_pilot_competitive` / `_pilot_matched` / `_pilot_pooled`, `workspace_mediation_positive_control` | The runs before the live test (paper Appendix A.8): the preliminary run (competitive arm, positive control in mode `estimate_pc`), one pilot study per arm (the competitive one with the positive control's SNR ladder; set its `principal_components_run` to the preliminary run's id first), and the positive control's runs (mode `control`, same settings record as the live arms). | No, settings only. |
| `workspace_mediation_pilot_tone` / `workspace_mediation_tone` | The tone variant of the on arm (paper §6.3, A.8): the competitive arm with `[audition].tone_rule = "error_ratio"`, as a pilot (role `pilot`) and as a live run (role `test`, with the settings record). Every other workspace-mediation study runs the categorical tone rule, and the boot refuses a study whose tone rule is not its own. | No, settings only. |
| `tier0` / `tier1` / `tier2` / `tier3` | Deployment-tier hardware hints, selected by `KAINE_TIER` or `[deployment].tier`. These overlays are inert by contract and never enable a module. Combine a tier with your own module choices in `config/kaine.operator.toml`. See [Choosing a deployment](../07-deployment/README.md). | No, hardware hints only. |

## Secrets file

`config/secrets.toml` is gitignored. Copy [`config/secrets.example.toml`](../../config/secrets.example.toml) to `config/secrets.toml` and fill in the real values. Set restrictive permissions:

```bash
chmod 600 config/secrets.toml
```

Real secret values are never printed in documentation or committed to the repository. `config/secrets.toml` is read by individual subsystems rather than being merged into the main config stack, all through one loader (`kaine.secrets_file.load_secrets_doc`). A missing file is empty. A file that exists but cannot be read is treated as absent with one warning, so containers, which get every secret from the environment and do not mount the file, run without it. A malformed file is an error.

### Environment overrides

Environment variables override the merged TOML where the code reads them. They do not always win over every secret source:

- A `[language].api_key` set in config takes precedence over `KAINE_MODEL_SERVER_API_KEY`.
- The organ address defaults to `http://127.0.0.1:11434/v1` when `[language].chat_url` is unset. The organ default, the model-server key lookup and the free-disk floor are defined once, in `kaine/defaults.py`.
- Per-consumer `[episodic_memory|social_cognition.qdrant].api_key` values take precedence over `KAINE_QDRANT_API_KEY` and any secrets-file value.
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
| `KAINE_DASHBOARD_TOKEN` | Dashboard operator token |
| `KAINE_DASHBOARD_HOST` | `[dashboard].host` |
| `KAINE_DASHBOARD_PORT` | `[dashboard].port` |
| `KAINE_DASHBOARD_CONVERSATION_ENABLED` | `[dashboard].conversation_enabled` |
| `KAINE_DASHBOARD_NON_LOOPBACK_ALLOWED` | `[dashboard].non_loopback_allowed` |
| `KAINE_DASHBOARD_ALLOWED_ORIGINS` | `[dashboard].allowed_origins` |
| `KAINE_DASHBOARD_ACCESS` | `[dashboard].access` (`open` or `token`) |
| `KAINE_DASHBOARD_READ_ONLY` | `[dashboard].read_only` |
| `KAINE_DASHBOARD_EXTRA_HOSTS` | Extra tailnet or reverse-proxy host names |
| `KAINE_STATE_KEY` | State encryption key |
| `KAINE_MODEL_SERVER_API_KEY` | Model server API key, read when `[language].api_key` is unset |
| `KAINE_ORGAN_URL` | Organ address for the sleep module trainer service, which runs without the config |
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
| `api_key` | Qdrant API key. Generate with `openssl rand -hex 32`. Must match `compose/.env`. Required by the episodic memory and social cognition modules when `backend = "qdrant"`. A per-consumer `[episodic_memory|social_cognition.qdrant].api_key` takes precedence. |

### Dashboard secrets

Put the dashboard operator token under `[dashboard]` in `config/secrets.toml`, not in `config/kaine.toml` or `config/kaine.operator.toml`. If a non-empty `operator_token` appears in a non-secrets file, the dashboard refuses to start. When a token is set, it must be at least 32 characters long. The shipped `[dashboard].access` is `"open"`; set it to `"token"` (or set `KAINE_DASHBOARD_ACCESS=token`) to require the operator token. Full `[dashboard]` network and token settings are on the [Security and Dashboard](security-and-dashboard.md) page.

### Caretaker tokens

Store caretaker authentication tokens under `[caretaker.tokens]` in `config/secrets.toml`, or in the environment as `KAINE_CARETAKER_TOKEN_<NAME>` (the channel's `token_name`, upper-cased), which wins over the file. The containers read only the environment: put the lines in `compose/caretaker.env`.

## Section guide

The detailed reference is split across these pages:

- [Core, cycle and host](core.md): `[redis]`, `[storage]`, `[hardware]`, `[tier]`, `[deployment]`, `[services.<name>]`, `[bus]`, `[preboot]`, `[gpu_preflight]`, `[cycle]`, `[cycle.access_rate]`, `[workspace]`, `[action_selection]`, `[oscillator]`, `[experiment]`, `[logging]`, `[remote_bridge]`, `[modules]`, `[plugins]`, and `[supervisor]`.
- [Modules](modules.md): per-module sections such as `[interoception]`, `[sequence]`, `[vision]`, `[planning]`, `[episodic_memory]`, `[self_model]`, `[affect]`, `[effectors]`, `[language]`, `[audition]`, `[vocal]`, `[social_cognition]`, `[world_model]`, `[embodiment]`, `[perception]`, and `[embedding]`.
- [Perception feed and sleep](perception-and-sleep.md): `[perception_feed]`, `[perception_feed.stimulus_source]`, `[perception_preview]`, `[sleep]`, and `[sleep.voice_alignment]`.
- [Lifecycle, evaluation and research](lifecycle-and-research.md): `[evaluation]`, `[individuation]`, `[lifecycle]`, `[developmental_stage]`, `[caretaker]`, `[preservation]`, `[research]`, `[transfer]`, `[research_submission]`, `[research_event_log]`, and `[ignition_log]`.
- [Security and Dashboard](security-and-dashboard.md): `[dashboard]`, `[security.state_encryption]`, and related security settings.
- [Deprecated names](deprecated-names.md): the names from before the module rename that are still read, and the last release that reads them.

For the structure and behaviour of individual modules, see the module pages under [The modules](../09-modules/README.md).
