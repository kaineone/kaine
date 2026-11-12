## ADDED Requirements

### Requirement: Speech ladders over the existing backends
KAINE SHALL define ordered `(backend, model id)` speech ladders, heaviest first: TTS (`chatterbox`, then `sherpa_onnx`/`kokoro-en`) and STT (`speaches`, then `sherpa_onnx`/`moonshine-base-en`, then `sherpa_onnx`/`moonshine-tiny-en`). Shipped defaults SHALL remain `chatterbox` and `speaches`. A rung SHALL determine only the engine and model, not the organ's interface or module semantics.

#### Scenario: A lighter STT rung keeps the organ contract
- **WHEN** Audition runs on `sherpa_onnx` with `moonshine-tiny-en` instead of `speaches`
- **THEN** Audition publishes the same event types with the same payload shapes, and no other module's behaviour changes

#### Scenario: Existing deployments are unchanged
- **WHEN** a configuration with no speech backend keys, or with the current defaults, is used on any existing host
- **THEN** the resolved speech backends are `chatterbox` and `speaches`, exactly as before this change

### Requirement: Automatic selection picks the heaviest rung that fits
The system SHALL select the heaviest installed rung whose calibrated footprint fits the budget. It SHALL NOT select absent models, and ladder traversal SHALL NOT download anything. When the best rung is absent, the next installed rung SHALL serve with a hint naming the consent-gated acquisition command, the model's size and licence.

#### Scenario: 8 GB unified host lands on the sherpa rungs
- **WHEN** the budget of an 8 GB unified-memory host cannot hold Chatterbox or Speaches `medium.en` alongside the pinned organ, and the sherpa models are installed
- **THEN** TTS runs on `sherpa_onnx` with `kokoro-en` and STT on `sherpa_onnx` with `moonshine-base-en`, and the selection is surfaced with the reason that the heavier rungs do not fit beside the organ

#### Scenario: Missing weights surface a hint, not a download
- **WHEN** the best-fitting STT rung is `moonshine-base-en` but only `moonshine-tiny-en` is installed
- **THEN** STT runs on `moonshine-tiny-en`, KAINE surfaces that `moonshine-base-en` is not installed with the command, size and licence needed to acquire it, and nothing is downloaded

### Requirement: The host probe recommends, the operator chooses
The wizard SHALL recommend speech rungs from the fit report. The recommendation SHALL be applied only on operator acceptance; the effective backend SHALL always be the operator's choice. When the operator keeps a heavier rung than recommended, KAINE SHALL honour it and surface the expected cost.

#### Scenario: Recommendation on an 8 GB unified-memory host
- **WHEN** the wizard runs on a host with about 8 GB of unified memory whose fit report shows the heavy speech rungs cannot co-reside with the organ
- **THEN** it recommends the `sherpa_onnx` rungs with the reason, and applies them only if the operator accepts

#### Scenario: Operator keeps the heavy rung
- **WHEN** the operator declines the recommendation and keeps `chatterbox` on that host
- **THEN** KAINE keeps `chatterbox`, states that each spoken turn will swap the organ and Chatterbox and that time-to-first-audio will be dominated by loads, and does not change the configuration

### Requirement: Downgrades are surfaced with reasons
When a speech rung cannot load or be admitted, KAINE SHALL substitute the next lighter installed rung and surface the failed rung, the reason, and the substitute in runtime status. A speech organ SHALL be disabled only when no rung can load, with the reason and rungs attempted surfaced. No downgrade or disablement SHALL be silent.

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
KAINE SHALL measure every spoken turn's time-to-first-audio and its segments, recording cold-path and warm-path turns separately. Persistent target misses SHALL be surfaced with the responsible segment. Reference-class targets (8 GB unified, sherpa rungs, 2-4B organ): warm TTFA 1.5 s, cold 4 s, STT 300 ms, organ first token 800 ms, TTS first chunk 150 ms. Measured results SHALL be published with the change.

#### Scenario: Warm turn is measured against its target
- **WHEN** every rung in the voice loop is resident and a turn completes
- **THEN** its time-to-first-audio and segment breakdown are recorded as a warm-path turn and available in residency status

#### Scenario: A cold turn's miss names its cause
- **WHEN** a turn exceeds its target because a rung had to load
- **THEN** the turn is recorded as cold-path with the load segment showing the cost, and repeated misses are surfaced as a degradation report
