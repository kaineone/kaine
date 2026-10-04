# runtime-backends Specification

## Purpose
This capability lets heavy modules choose an interchangeable model runtime backend behind a stable internal client interface, so a backend failure degrades rather than crashing boot. The backend choice does not alter event shapes, subscriptions, or cognitive semantics.

## Requirements

### Requirement: Heavy components select an interchangeable runtime backend

Each module that loads a heavy model SHALL select its model runtime through a
`[<module>].backend` configuration key resolved behind the module's existing
internal client interface. Selecting a backend SHALL NOT change the module's
published event shapes, its bus subscriptions, or its cognitive semantics — only
which implementation realizes the organ.

The default backend for every component SHALL reproduce the current
workstation ("Tier 2") behavior exactly, so that a config with no backend keys
behaves identically to today.

Backends SHALL be lazy-imported: a backend's third-party dependency is imported
only when that backend is selected, so an install for one tier does not require
another tier's dependencies.

#### Scenario: Default backend preserves current behavior

- **WHEN** the system boots with no `[<module>].backend` keys set
- **THEN** every heavy module loads its current default runtime (Ollama,
  faster-whisper, Chatterbox, torch-DINOv2, sentence-transformers, Qdrant)
- **AND** the published event shapes are unchanged

#### Scenario: Edge backend is functionally substitutable

- **WHEN** Lingua's backend is set to the llama.cpp/GGUF engine
- **THEN** Lingua emits the same speech and evaluation events as under Ollama
- **AND** the A/B-divergence baseline still uses the same model as the organ

#### Scenario: Unselected backend imports nothing

- **WHEN** a backend is not selected
- **THEN** its third-party runtime dependency is not imported at boot

### Requirement: A failed backend degrades, it does not crash the boot

A module whose configured backend cannot load on the current host SHALL either
fall back to a declared lighter backend or disable itself, in both cases logging
a structured reason and surfacing it on the operator health surface. A backend
load failure (missing dependency or load error) SHALL NOT raise into the boot
path.

A capability removed this way SHALL be reported, not silent.

#### Scenario: Missing backend dependency disables the module with a reason

- **WHEN** a module's configured backend fails to import
- **AND** no lighter fallback backend is declared
- **THEN** the module is not registered
- **AND** a structured warning naming the module and the failed backend is
  logged and surfaced on the health surface
- **AND** the cognitive cycle boots and runs without that module

### Requirement: Lingua's HTTP backend is named for its protocol
Lingua's default backend SHALL be named `"openai"`, for the OpenAI-compatible HTTP server that serves the organ. The name `"ollama"` SHALL remain accepted as an alias that builds the same client. The in-process `llama_cpp` backend SHALL fall back to `"openai"`. The shipped tier profiles SHALL select `"openai"`.

#### Scenario: Both names build the same client
- **WHEN** Lingua's backend is `"openai"`, `"ollama"`, or unset
- **THEN** the registry builds the OpenAI-compatible HTTP client

#### Scenario: The shipped profiles use the canonical name
- **WHEN** the tier2 or tier3 profile is read
- **THEN** its `[lingua].backend` is `"openai"`
