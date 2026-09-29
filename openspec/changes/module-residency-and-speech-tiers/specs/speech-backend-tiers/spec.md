## ADDED Requirements

### Requirement: Speech ladders over the existing backends
KAINE SHALL define the speech ladders as ordered `(backend, model id)` rungs over the existing `[vox].backend` and `[audition].backend` values and the sherpa-onnx model ids, heaviest first:

- TTS: `chatterbox`, then `sherpa_onnx` with `kokoro-en`;
- STT: `speaches` (faster-whisper `medium.en`), then `sherpa_onnx` with `moonshine-base-en`, then `sherpa_onnx` with `moonshine-tiny-en`.

The shipped defaults SHALL remain `chatterbox` for TTS and `speaches` for STT, so existing dual-GPU x86_64 workstation, ROCm, XPU, MPS and CPU-only deployments are unaffected. A rung SHALL determine only which engine and model realise the organ; it SHALL NOT change the organ's interface, the cognitive cycle, the workspace or any module's semantics. When and where a rung's model is resident SHALL remain governed by the residency manager. An unrecognized backend value SHALL continue to be rejected as `runtime-backends` specifies.

#### Scenario: A lighter STT rung keeps the organ contract
- **WHEN** Audition runs on `sherpa_onnx` with `moonshine-tiny-en` instead of `speaches`
- **THEN** Audition publishes the same event types with the same payload shapes, and no other module's behaviour changes

#### Scenario: Existing deployments are unchanged
- **WHEN** a configuration with no speech backend keys, or with the current defaults, is used on any existing host
- **THEN** the resolved speech backends are `chatterbox` and `speaches`, exactly as before this change

### Requirement: Automatic selection picks the heaviest rung that fits
When the residency manager selects a speech rung automatically, it SHALL consider only rungs whose models are installed and whose calibrated footprint can be admitted within the budget, and SHALL choose the heaviest such rung. It SHALL NOT select a rung whose model is absent, and ladder traversal SHALL NOT download or install anything. When the best-fitting rung's model is absent, the next installed rung SHALL serve, and KAINE SHALL surface a hint naming the consent-gated acquisition command (`python -m kaine.setup.speech_models`) with the model's name, size and licence.

#### Scenario: 8 GB unified host lands on the sherpa rungs
- **WHEN** the budget of an 8 GB unified-memory host cannot hold Chatterbox or Speaches `medium.en` alongside the pinned organ, and the sherpa models are installed
- **THEN** TTS runs on `sherpa_onnx` with `kokoro-en` and STT on `sherpa_onnx` with `moonshine-base-en`, and the selection is surfaced with the reason that the heavier rungs do not fit beside the organ

#### Scenario: Missing weights surface a hint, not a download
- **WHEN** the best-fitting STT rung is `moonshine-base-en` but only `moonshine-tiny-en` is installed
- **THEN** STT runs on `moonshine-tiny-en`, KAINE surfaces that `moonshine-base-en` is not installed with the command, size and licence needed to acquire it, and nothing is downloaded

### Requirement: The host probe recommends, the operator chooses
The first-run wizard SHALL recommend a TTS rung and an STT rung from the fit report, and the recommendation SHALL be advisory: it SHALL be applied only when the operator accepts it, and nothing SHALL rewrite the operator's configuration on its own. The effective backend SHALL always be the operator's choice: the shipped default, an explicit backend key, or an accepted recommendation. When the operator's choice is heavier than the recommendation, KAINE SHALL honour it and SHALL surface the expected cost, for example that the chosen engine will be time-multiplexed with the organ rather than co-resident.

#### Scenario: Recommendation on an 8 GB unified-memory host
- **WHEN** the wizard runs on a host with about 8 GB of unified memory whose fit report shows the heavy speech rungs cannot co-reside with the organ
- **THEN** it recommends the `sherpa_onnx` rungs with the reason, and applies them only if the operator accepts

#### Scenario: Operator keeps the heavy rung
- **WHEN** the operator declines the recommendation and keeps `chatterbox` on that host
- **THEN** KAINE keeps `chatterbox`, states that each spoken turn will swap the organ and Chatterbox and that time-to-first-audio will be dominated by loads, and does not change the configuration

### Requirement: Downgrades are surfaced with reasons
When the selected speech rung cannot load, cannot initialise or cannot be admitted, KAINE SHALL substitute the next lighter installed rung of the same ladder and SHALL surface, in the wizard or runtime status and not only in a log file, the rung that failed, the reason, and the rung now serving. A speech organ SHALL be disabled only when no rung of its ladder can load or be admitted, and the disablement SHALL be surfaced with its reason and the rungs attempted. No downgrade and no disablement SHALL be silent.

#### Scenario: TTS falls back to Kokoro
- **WHEN** `chatterbox` fails to load or cannot be admitted on a host where `kokoro-en` is installed
- **THEN** TTS runs on `sherpa_onnx` with `kokoro-en`, and the failed rung, the reason and the substitution are surfaced

#### Scenario: STT walks the whole ladder
- **WHEN** `speaches` fails and then `moonshine-base-en` fails to load
- **THEN** STT runs on `moonshine-tiny-en`, and each failure and substitution is surfaced with its reason

### Requirement: Consent before fetching speech assets
When a choice, an accepted recommendation or a downgrade would need speech model assets that are not present on the host, KAINE SHALL state what would be fetched, from where, at what size and under which licence, and SHALL fetch only after the operator consents, through the existing consent-gated acquisition path. Downgrades and ladder traversal SHALL NOT bypass this. Assets already present SHALL NOT be re-fetched or re-consented.

#### Scenario: Accepting a recommendation that needs downloads
- **WHEN** the operator accepts the `sherpa_onnx` recommendation on a host where neither sherpa model is present
- **THEN** KAINE shows each archive's name, source, size and licence (including the GPL-3.0-or-later espeak-ng data bundled with Kokoro) and downloads only after consent

### Requirement: Voice latency is measured per turn
KAINE SHALL measure every spoken turn's time-to-first-audio and its segments (`queue_wait`, `preempt_wait`, `load`, `stt`, `llm_first_token`, `tts_first_chunk`), SHALL record turns that paid a model load (cold path) separately from turns that did not (warm path), and SHALL surface persistent misses of the targets with the segment responsible. The targets for the reference class (8 GB unified memory, the `sherpa_onnx` speech rungs, a 2–4B 4-bit organ, all TTL-resident) SHALL be: time-to-first-audio at most 1.5 s warm and 4 s cold; STT final at most 300 ms warm; organ first token at most 800 ms warm; TTS first chunk at most 150 ms warm. These are targets, not guarantees, and the measured results on the reference hosts SHALL be published with the change.

#### Scenario: Warm turn is measured against its target
- **WHEN** every rung in the voice loop is resident and a turn completes
- **THEN** its time-to-first-audio and segment breakdown are recorded as a warm-path turn and available in residency status

#### Scenario: A cold turn's miss names its cause
- **WHEN** a turn exceeds its target because a rung had to load
- **THEN** the turn is recorded as cold-path with the load segment showing the cost, and repeated misses are surfaced as a degradation report
