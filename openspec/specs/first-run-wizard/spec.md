# first-run-wizard Specification

## Purpose
TBD - created by archiving change first-run-wizard. Update Purpose after archive.
## Requirements
### Requirement: Operator config-override layer
The system SHALL provide a shared `load_kaine_config()` that loads the shipped `config/kaine.toml`
and deep-merges an optional, gitignored `config/kaine.operator.toml` over it, with operator values
taking precedence (recursive merge of nested tables). The cycle entrypoint and the Nexus config
readers SHALL use this loader so operator overrides apply uniformly. The shipped `config/kaine.toml`
SHALL remain unchanged (all modules disabled); operator choices live only in the override file.

#### Scenario: Operator override wins
- **WHEN** `config/kaine.operator.toml` sets `[modules].soma = true` over a shipped `false`
- **THEN** `load_kaine_config()` returns `soma = true` while the shipped `config/kaine.toml` on disk
  is unchanged

#### Scenario: No override file is harmless
- **WHEN** `config/kaine.operator.toml` does not exist
- **THEN** `load_kaine_config()` returns the shipped configuration unchanged

#### Scenario: Nested tables merge, not replace
- **WHEN** the override sets one key inside a table that the shipped config also populates
- **THEN** the merged table contains the override's key plus the shipped table's other keys

### Requirement: Guided first-run wizard
The system SHALL provide a first-run wizard (`python -m kaine.setup`) that guides an operator through
configuration and writes only to `config/kaine.operator.toml`. It SHALL require an explicit typed
acknowledgement of the CAL Article 4 welfare obligations before configuring an entity; scan the host
via `describe_host()` and propose device assignments; let the operator select modules and record the
served model, voice, and STT identifiers; offer to install the optional extras implied by the chosen
modules on explicit confirmation; offer opt-in research-metrics submission; and print a summary with
the required environment gates and launch steps. The wizard SHALL NOT boot the entity and SHALL
support a non-interactive mode for testing.

#### Scenario: Welfare acknowledgement is required
- **WHEN** the operator does not give the CAL welfare acknowledgement
- **THEN** the wizard does not write an entity configuration

#### Scenario: Choices persist to the override file only
- **WHEN** the operator completes the wizard
- **THEN** the selections are written to `config/kaine.operator.toml` and `config/kaine.toml` is not
  modified

#### Scenario: Hardware scan proposes devices
- **WHEN** the host reports multiple GPUs
- **THEN** the wizard proposes a primary/secondary device assignment, falling back gracefully on a
  single-GPU or CPU-only host

#### Scenario: Metrics submission is opt-in
- **WHEN** the operator declines research participation
- **THEN** the wizard leaves `[research_submission].enabled` false

#### Scenario: The wizard never boots the entity
- **WHEN** the wizard finishes
- **THEN** no cognitive cycle is started; only configuration is written

### Requirement: Wizard detects and helps provision external dependencies

The first-run wizard SHALL detect the external service dependencies required by
the enabled modules and report, for each, whether it is already running. The
model backend dependency SHALL be a local **OpenAI-compatible model server**, not
Ollama, selected per GPU vendor along the same hardware-aware split the
trainer-provisioning path already uses: on **CUDA** hosts the backend is Unsloth
Studio; on **AMD/ROCm** hosts it is the unsloth-core toolchain's
OpenAI-compatible inference engine (ROCm `llama.cpp` `llama-server` or vLLM); on
hosts with no supported GPU the wizard SHALL guide the operator to a conforming
OpenAI-compatible server. Model discovery SHALL use the server's `/v1/models`
endpoint.
For dependencies provisionable by a single in-repo script or installer command,
the wizard SHALL show the exact command and run it ONLY on explicit operator
consent. For heavy GPU services that cannot be honestly installed in one step,
the wizard SHALL print real setup guidance and a docs link and run nothing. The
wizard SHALL NOT install anything without consent and SHALL NOT crash on a
provisioning failure.

#### Scenario: A running dependency is not offered

- **WHEN** a required service is already listening on its port
- **THEN** the wizard reports it as running and offers no install

#### Scenario: The model backend is the OpenAI-compatible server, not Ollama

- **WHEN** the wizard provisions the model backend for the enabled modules
- **THEN** it detects/guides a local OpenAI-compatible server per GPU vendor
  (Unsloth Studio on CUDA; the unsloth-core ROCm engine — `llama-server` or vLLM
  — on AMD/ROCm; a conforming server otherwise)
- **AND** it does not require or install Ollama
- **AND** model discovery queries `/v1/models`

#### Scenario: A command-provisionable dependency runs only on consent

- **WHEN** a required command-provisionable service (e.g. Redis) is not running
- **THEN** the wizard prints the exact command
- **AND** runs it only if the operator consents, otherwise prints how to run it later

#### Scenario: A heavy GPU service is guided, never auto-installed

- **WHEN** a required guide-only service (e.g. the model server, Speaches,
  Chatterbox) is not running
- **THEN** the wizard prints its setup steps and docs link
- **AND** never runs an install command for it

#### Scenario: A provisioning failure does not crash the wizard

- **WHEN** a consented provisioning command fails
- **THEN** the wizard reports the failure and the manual command
- **AND** continues to the next step without raising

### Requirement: Hardware-aware sleep-trainer provisioning
The setup flow SHALL select sleep-cycle voice-alignment trainer guidance from
the detected GPU vendor (`kaine.hardware.describe_host()["backend"]`): a CUDA
host SHALL be guided to Unsloth Studio, an AMD/ROCm host to unsloth-core, and a
host with no CUDA/ROCm GPU SHALL be told the GPU trainer is unavailable (the
voice-alignment phase stays off; the consolidation-divergence metric still
emits without training). The flow SHALL detect a usable trainer interpreter with
a real probe (the interpreter exists AND can `import unsloth`) rather than a
faked result, MUST NOT auto-install the multi-gigabyte trainer environment
(guidance only), and on a successful probe MAY offer to record the interpreter
as `[hypnos.voice_alignment].trainer_python` in the operator config.

#### Scenario: NVIDIA host is guided to Unsloth Studio
- **WHEN** the setup flow runs trainer provisioning and `describe_host()["backend"]` is `"cuda"`
- **THEN** it presents Unsloth Studio guidance (doc URL + steps) and, if a usable Studio interpreter is detected by the probe, offers to set `trainer_python` to it — without auto-installing the environment

#### Scenario: AMD host is guided to unsloth-core
- **WHEN** trainer provisioning runs and the backend is `"rocm"`
- **THEN** it presents unsloth-core guidance (not Studio), with the same detect-and-offer-to-set behavior

#### Scenario: No GPU trainer available
- **WHEN** the backend is `"cpu"`, `"mps"`, or `"xpu"`
- **THEN** the flow reports that sleep-cycle voice-alignment training is unavailable on this host and does not error — the phase stays off and the consolidation-divergence metric still emits without training

#### Scenario: Detection never fakes a result
- **WHEN** the probed interpreter is absent or cannot `import unsloth`
- **THEN** the flow reports the trainer as not yet usable (with the install guidance) and never records a `trainer_python` that would fail at the first sleep cycle

### Requirement: Perception-feed extras are provisioned for research installs

The wizard's extras inference SHALL imply the perception-feed decode/capture
dependencies from the configured `[perception_feed].mode`, independently of each
module's `capture_enabled` flag, so a fresh research install can decode playlist
media. When `mode` is `playlist` (decodes media) or `live` (opens devices),
`implied_extras` SHALL add both the `vision` extra (OpenCV video track) and the
`audio` extra (which provisions PyAV `av` for the playlist audio track, plus the
microphone deps). When `mode` is `seeded` (pure-numpy synthesis) it SHALL add
neither. The returned extras list SHALL be de-duplicated. The aggregate
`perception` extra SHALL pull both `audio` and `vision`, and the installer
(`scripts/install.sh` and `scripts/install.py`) SHALL provide a `--research` flag
that runs a real `pip install -e .[perception]` after the lean base install, with
the default install left unchanged.

#### Scenario: Playlist feed implies both surfaces' extras

- **WHEN** the configured `[perception_feed].mode` is `playlist`
- **THEN** `implied_extras` includes both `vision` and `audio` (the latter carries
  PyAV for the playlist audio-track decode), regardless of the per-module
  `capture_enabled` flags

#### Scenario: Live feed implies both surfaces' extras

- **WHEN** the configured `[perception_feed].mode` is `live`
- **THEN** `implied_extras` includes both `vision` and `audio`

#### Scenario: Seeded feed implies no decode extras

- **WHEN** the configured `[perception_feed].mode` is `seeded`
- **THEN** `implied_extras` adds neither `vision` nor `audio` for the feed (seeded
  synthesis needs no cv2 or av), and any extras it returns are de-duplicated

#### Scenario: The research install provisions the perception extras

- **WHEN** an operator runs `scripts/install.sh --research` (or its `install.py`
  port) on a fresh machine
- **THEN** after the lean base install it runs a real `pip install -e .[perception]`
  (audio + vision, including PyAV) and reports what it installed, while a default
  install without `--research` stays lean

