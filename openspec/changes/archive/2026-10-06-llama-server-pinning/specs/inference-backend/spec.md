## ADDED Requirements

### Requirement: The model server is pinned and its memory settings are explicit
Every committed definition of the model server (compose for CUDA, ROCm and CPU, and the quadlet unit) SHALL default to a llama.cpp server image pinned by digest, and the trainer's converter SHALL use the same llama.cpp build. Each organ command line SHALL state its GPU layer count with automatic fitting off, its prompt-cache RAM limit and its KV-cache type, and SHALL NOT enable slot saving.

#### Scenario: A fresh install pulls the server image
- **WHEN** an install starts the model server without overriding the image
- **THEN** it runs the digest-pinned build that the converter also uses

#### Scenario: The GPU lacks room for every layer
- **WHEN** the organ starts with automatic fitting off on a GPU that cannot hold every requested layer
- **THEN** the load fails loudly instead of silently offloading part of the model to the CPU

#### Scenario: A definition enables slot saving
- **WHEN** a committed model-server definition passes `--slot-save-path`
- **THEN** the definitions test fails
