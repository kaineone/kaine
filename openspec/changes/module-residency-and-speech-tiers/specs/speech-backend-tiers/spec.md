## ADDED Requirements

### Requirement: Speech backend selection keys

The speech configuration SHALL accept a `backend` key for text-to-speech (TTS) and a `backend` key for speech-to-text (STT), each naming the engine that realizes the organ. The recognized TTS values SHALL be Chatterbox, Kokoro, KittenTTS, and Piper; the recognized STT values SHALL be Speaches (serving faster-whisper), Moonshine, and whisper.cpp. The shipped defaults SHALL remain Chatterbox for TTS and Speaches running faster-whisper `medium.en` for STT, so that existing dual-GPU x86_64 workstation, ROCm, XPU, MPS, and CPU-only deployments are unaffected. The `backend` key SHALL determine only which engine realizes the organ — it SHALL NOT change the organ's interface, the cognitive cycle, the workspace, or any module's semantics, and when and where the chosen engine's model is resident SHALL remain governed by the residency scheduler. An unrecognized `backend` value SHALL be rejected at configuration validation with the accepted values listed, and SHALL NOT be silently mapped onto another engine.

#### Scenario: TTS backend selection
- **WHEN** the operator sets the TTS `backend` key to `kokoro` on a host that can run it
- **THEN** the speech organ produces speech through Kokoro, the organ's contract with the rest of KAINE is unchanged, and no other module's behavior changes

#### Scenario: STT backend selection
- **WHEN** the operator sets the STT `backend` key to `moonshine`
- **THEN** the speech organ transcribes through Moonshine, the organ's contract with the rest of KAINE is unchanged, and no other module's behavior changes

#### Scenario: Unrecognized backend value
- **WHEN** the operator sets a `backend` key to a value KAINE does not recognize
- **THEN** configuration validation fails with the accepted values listed, and KAINE does not silently fall back to a different engine

### Requirement: Host probe recommends, operator chooses

The host probe SHALL recommend a TTS rung and an STT rung from the measured resources of the host, and its recommendation SHALL be advisory: KAINE SHALL present the recommendation to the operator as a choice, SHALL apply it only when the operator accepts it, and SHALL never let the probe modify configuration on its own. The effective backend SHALL always be the operator's choice — the shipped default where no choice has been made, an explicit `backend` key, or a recommendation the operator accepted. On hosts whose binding constraint is a small unified or total memory budget, the probe SHALL recommend Kokoro for TTS and Moonshine for STT, and SHALL NOT recommend Piper as the lightweight rung. Where the operator's choice is heavier than the recommendation, KAINE SHALL honor the choice and SHALL surface an honest statement of the expected cost — for example, that the chosen engine's weights must be made resident within the same memory budget as the language-model tier and will be time-multiplexed rather than co-resident.

#### Scenario: Recommendation on an 8 GB unified-memory host
- **WHEN** the host probe examines a first-run host with roughly 8 GB of unified CPU/GPU memory, no discrete GPU, and a fast NVMe — a Jetson Orin Nano class board
- **THEN** the probe recommends Kokoro for TTS and Moonshine for STT, states why (the unified-memory budget cannot hold Chatterbox or Speaches `medium.en` comfortably alongside the language-model tier, while Kokoro's ~327 MB ONNX footprint and Moonshine's variable-length, sub-200 ms segments fit a time-multiplexed residency), explicitly does not recommend Piper despite its common reputation as the lightweight option, and presents the recommendation as a choice rather than applying it

#### Scenario: Operator overrides the recommendation
- **WHEN** the operator chooses Chatterbox for TTS on the 8 GB unified-memory host against the probe's Kokoro recommendation
- **THEN** KAINE configures Chatterbox as chosen, surfaces an honest statement of the expected cost (pressure on the unified-memory budget and increased time-multiplexing of model residency), and the probe never rewrites the operator's choice

#### Scenario: Workstation and accelerator defaults are preserved
- **WHEN** the probe examines a host with ample discrete VRAM such as the existing dual-GPU x86_64 workstation, or an existing deployment whose configuration contains no `backend` keys
- **THEN** the recommendation is the current default pair or no change, and existing ROCm, XPU, MPS, and CPU-only deployments continue running their current engines unchanged

### Requirement: KittenTTS is opt-in only

KittenTTS SHALL be selectable only by the operator explicitly naming it in the TTS `backend` key. No shipped default, probe recommendation, or downgrade path SHALL select KittenTTS, and no KittenTTS package SHALL be downloaded or loaded without that explicit operator choice. When the operator does select it, KAINE SHALL surface, before any download or load, that KittenTTS is a v0.8 developer preview whose nano INT8 variant has known reported issues.

#### Scenario: KittenTTS is never selected automatically
- **WHEN** any automatic selection path runs — the shipped default on a fresh install, the probe producing its recommendation, or the TTS downgrade ladder stepping down after a load failure
- **THEN** KittenTTS is not among the candidates: the recommendation and the downgrade land on Kokoro or on a surfaced last-resort disable, never on KittenTTS, and no KittenTTS model is fetched or loaded unless the operator explicitly configured it

#### Scenario: Explicit opt-in surfaces the preview caveat
- **WHEN** the operator explicitly sets the TTS `backend` key to KittenTTS
- **THEN** KAINE surfaces the v0.8 developer-preview caveat and the known nano INT8 issues before any download, loads KittenTTS only after the operator confirms, and no other code path ever substitutes KittenTTS for another engine

### Requirement: Piper is a compatibility rung, not the lightweight default

Piper SHALL remain selectable as a compatibility rung for operators with existing Piper voices or deployments, and SHALL NOT be the shipped lightweight default, the probe's lightweight recommendation, or the rung chosen automatically when a light TTS engine is needed — that rung SHALL be Kokoro. When Piper is selected, KAINE SHALL surface its measured cost honestly (2026 benchmarks place it at roughly 2.6 GB peak memory and roughly 1720 ms to first audio, worse than Kokoro on both axes) and SHALL NOT present it as the small-hardware answer.

#### Scenario: Piper is not the lightweight default
- **WHEN** a lightweight TTS rung must be recommended or selected automatically on any host — probe recommendation, first-run suggestion, or downgrade
- **THEN** the rung is Kokoro and never Piper, and Piper is offered only as an explicitly chosen compatibility option

#### Scenario: Operator selects Piper for compatibility
- **WHEN** the operator explicitly sets the TTS `backend` key to Piper, for example to reuse existing Piper voice models
- **THEN** KAINE runs Piper as chosen and surfaces its measured memory and latency cost alongside the choice, without describing it as the lightweight option

### Requirement: Downgrade with surfaced reason on load failure

When the selected TTS or STT backend cannot load or cannot initialize, KAINE SHALL substitute the next lighter rung in the same ladder that the host can run — for TTS: Chatterbox, then Kokoro; for STT: Speaches (faster-whisper), then Moonshine, then whisper.cpp tiny/base — and SHALL surface to the operator, through the wizard or status output and not only in a log file, the engine that failed, the reason it failed, and the substitution made. KittenTTS and Piper SHALL be excluded from automatic substitution. An organ SHALL be disabled only as a last resort, when no rung in its ladder can load, and even then the disable SHALL be surfaced with its reason and with the manual opt-ins (KittenTTS, Piper) noted. No downgrade and no disable SHALL be silent.

#### Scenario: TTS backend failure downgrades with reason
- **WHEN** the configured TTS backend Chatterbox fails to load on the 8 GB unified-memory host, for example because its weights cannot be made resident within the memory budget
- **THEN** KAINE substitutes Kokoro, surfaces the failed engine, the failure reason, and the substitution to the operator, and the voice loop continues with Kokoro

#### Scenario: STT backend failure downgrades with reason
- **WHEN** the configured STT backend Speaches (faster-whisper `medium.en`) fails to load
- **THEN** KAINE substitutes Moonshine and surfaces the reason and the substitution, and if Moonshine also fails, substitutes whisper.cpp tiny/base with the reason surfaced at each step

#### Scenario: Disable is the last resort
- **WHEN** every automatic rung in an organ's ladder fails to load
- **THEN** the organ is disabled, the disable and its reason are surfaced prominently with the manual opt-ins noted, and KAINE never disables the organ silently or as the first response to a single load failure

### Requirement: Consent before fetching speech backend assets

When an operator's choice, an accepted recommendation, or a downgrade substitution requires downloading or installing model assets that are not already present on the host, KAINE SHALL state what will be fetched, from where, and at what size, and SHALL proceed only after the operator consents. This SHALL apply to every rung — Chatterbox weights, the Kokoro ONNX bundle, Moonshine's `.ort` model, Piper voices, and KittenTTS packages — and the downgrade path SHALL NOT bypass it.

#### Scenario: Consent before a recommended rung is fetched
- **WHEN** the operator accepts the probe's recommendation of Kokoro and Moonshine on a host where neither model's assets are present locally
- **THEN** KAINE states the download size and source for each and proceeds only after the operator consents, and assets already on disk are not re-fetched or re-consented on later runs

### Requirement: Speech ladder definition and traversal

KAINE SHALL define the TTS and STT ladders with the rungs and figures of this specification, SHALL automatically select only installed `auto` rungs that fit the budget, SHALL exclude `opt-in` rungs (KittenTTS) and the `compat` rung (Piper) from automatic selection, and SHALL NOT download weights or install engines as a side effect of ladder traversal without operator consent.

#### Scenario: 8 GB host defaults to Kokoro and Moonshine
- **WHEN** speech is configured on a host whose budget cannot hold Chatterbox alongside the pinned chat model
- **THEN** the selected rungs are Kokoro-82M for TTS and Moonshine for STT, and the selection — including why Chatterbox was excluded — is surfaced.

#### Scenario: Opt-in rungs are never silent fallbacks
- **WHEN** ladder traversal reaches KittenTTS or Piper without explicit operator configuration naming them
- **THEN** those rungs are skipped, the skip is recorded in the surfaced reason, and no automatic path ever selects them.

#### Scenario: Missing weights surface a hint, not a download
- **WHEN** the best-fitting rung's artifact is `absent`
- **THEN** the manager serves the next installed rung, surfaces "Kokoro not installed — using \<rung\>; run `kaine install tts-standard` (≈327 MB) to upgrade", and performs no download without consent.

### Requirement: Voice latency targets and measurement

KAINE SHALL measure time-to-first-audio and its contributing segments for every speech turn against the targets below, SHALL record cold-path turns separately from warm-path turns, and SHALL surface any target miss with the breakdown segment responsible.

Targets for the reference budget class — 8 GB unified memory, Kokoro + Moonshine + a 3–4B 4-bit chat model, all TTL-resident:

| Metric | Definition | Warm | Cold (one rung loads) |
|---|---|---|---|
| **TTFA** (time-to-first-audio) | end of user speech → first audio sample at the speaker | **≤ 1.5 s** | ≤ 4 s |
| STT final | end of speech → final transcript (utterance ≤ 10 s) | ≤ 300 ms | ≤ 1.5 s |
| LLM first token | prompt ready → first token | ≤ 800 ms | ≤ 8 s incl. load |
| TTS first chunk | sentence ready → first audio chunk | ≤ 150 ms | ≤ 2 s incl. load |
| Preemption grace | preempt signal → background residency released | ≤ 2 s (hard 10 s) | — |
| First turn after boot | all rungs cold | — | ≤ 15 s (prewarm removes this) |

The warm TTFA budget composes: 300 ms STT + 800 ms first token + 150 ms first chunk ≈ 1.25 s ≤ 1.5 s. It works because TTS is fed sentence-by-sentence from the streaming LLM, so TTFA does not wait for full generation, and because Moonshine's variable-length segments mean STT latency tracks the utterance rather than a fixed 30-second chunk. These are targets, not guarantees: every turn is measured into a breakdown `{queue_wait, preempt_wait, load, stt, llm_first_token, tts_first_chunk}`, cold-path turns are recorded separately from warm-path turns, and persistent misses surface as degradation reports naming the offending segment.

#### Scenario: Warm turn meets TTFA
- **WHEN** all rungs in the voice loop are TTL-resident and a turn completes
- **THEN** the measured end-of-speech to first-audio interval is ≤ 1.5 s and the full breakdown is available in the status surface.

#### Scenario: Miss is surfaced with its cause
- **WHEN** a turn's TTFA exceeds its target because a rung had to load
- **THEN** the turn is recorded as cold-path, the load segment of the breakdown shows the cost, and repeated misses surface a degradation report rather than passing silently.