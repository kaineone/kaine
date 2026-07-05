# first-run-wizard (delta)

## ADDED Requirements

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
