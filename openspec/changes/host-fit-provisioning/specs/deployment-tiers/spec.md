## ADDED Requirements

### Requirement: Tier recommendation accounts for memory, keeps the GPU, and bounds only backends
The tier recommender SHALL compute a memory budget as system RAM on unified-memory
hosts and the smaller of system RAM and total VRAM across GPUs on discrete hosts.
Nominal threshold sizes SHALL be compared against reported memory times 0.9. It
SHALL recommend: Tier 3 for two or more accelerators with a budget of at least
16 GB; Tier 2 for one accelerator with a budget of at least 16 GB; Tier 2 with
module residency required for an accelerator host with a budget from 6 GB up to
16 GB; Tier 1 below 6 GB or without an accelerator; Tier 0 when torch is absent,
on 32-bit ARM, or when RAM is below the nominal 4 GB floor (with the same 0.9
allowance).

The first-run wizard SHALL show the recommendation with its reason and the memory
budget, and SHALL record the matching tier as `[deployment].tier` in the
operator's local configuration only when the operator explicitly confirms. The
tier SHALL be applied as its own configuration layer between the shipped
defaults and the module-selection profile (the base-thesis `thesis_test` profile
by default, or `--profile` / `KAINE_PROFILE`) and the operator's configuration,
so recording a tier never replaces the selected module set; the cycle and the
pre-boot check SHALL load configuration through the same layering.

A tier file SHALL only bound backends and devices; it SHALL NOT enable or disable
modules. A tier file that contains a `[modules]` section or an
`[oscillator].enabled` key SHALL be refused with `ProfileError`. Each tier file
SHALL carry an advisory `[tier]` table with `name`, `unsupported_modules`, and
`oscillator_supported`. The pre-boot check SHALL include a `Tier fit` row: it SHALL
FAIL naming any enabled module in `unsupported_modules` or an enabled oscillator
when `oscillator_supported` is false, with the fix to disable them in the operator
config or record a larger tier; it SHALL PASS when they fit; it SHALL SKIP when
no tier is recorded; and it SHALL FAIL on a malformed `[tier]` table.

#### Scenario: 8 GB unified Jetson
- **WHEN** the host has one unified-memory accelerator and 8 GB of RAM
- **THEN** the recommender proposes Tier 2 with module residency required and does not recommend the CPU-only Tier 1

#### Scenario: Operator declines the recommendation
- **WHEN** the wizard proposes a tier and the operator declines
- **THEN** no tier is written and the existing configuration is unchanged

#### Scenario: Recorded tier keeps the base-thesis modules
- **WHEN** the operator accepts a Tier 2 recommendation and later boots without `--profile` or `KAINE_PROFILE`
- **THEN** the cycle loads the base-thesis module set with the Tier 2 backend settings layered on top, and the pre-boot check validates the same merged configuration

#### Scenario: Tier file with [modules] is refused
- **WHEN** an operator attempts to use a tier file that contains a `[modules]`
  section or `[oscillator].enabled = true`
- **THEN** `ProfileError` is raised and the file is refused, because tiers only
  bound backends and devices and must not toggle modules

#### Scenario: Tier fit fails when tier0 is recorded with topos enabled
- **WHEN** the recorded tier is tier0 and the operator config has `topos.enabled = true`
- **THEN** the pre-boot Tier-fit row FAILS, naming topos as unsupported at tier0
  and advising the operator to disable it or record a larger tier
