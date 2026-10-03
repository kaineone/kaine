## ADDED Requirements

### Requirement: The hardware overlays cover every GPU-reserving service
`compose/kaine.cpu.yml` SHALL remove the GPU reservation from every service in `compose/kaine.yml` that reserves one, including `kaine-study` and `kaine-trainer`, and SHALL give image-built KAINE services the CPU image. `compose/kaine.single-gpu.yml` SHALL place every GPU-reserving service on card 0.

#### Scenario: The CPU overlay leaves no GPU reservation
- **WHEN** the stack is rendered from `compose/kaine.yml` with `compose/kaine.cpu.yml`
- **THEN** no service reserves a GPU device

#### Scenario: The single-GPU overlay uses only card 0
- **WHEN** the stack is rendered from `compose/kaine.yml` with `compose/kaine.single-gpu.yml`
- **THEN** every GPU reservation names device 0
