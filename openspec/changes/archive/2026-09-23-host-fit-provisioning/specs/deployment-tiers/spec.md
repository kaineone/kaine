## ADDED Requirements

### Requirement: Tier recommendation accounts for memory, keeps the GPU, and bounds only backends
The tier recommender SHALL compute a memory budget as system RAM on unified-memory
hosts and the smaller of system RAM and total VRAM across GPUs on discrete hosts.
Nominal threshold sizes SHALL be scaled by 0.9 and applied as floors on reported
memory (a nominal 16 GB threshold becomes a 14.4 GiB floor; a nominal 6 GB
threshold becomes 5.4 GiB; the Tier-0 4 GB nominal floor becomes 3.6 GiB). It
SHALL recommend: Tier 3 for two or more accelerators with a budget of at least the
16 GB floor; Tier 2 for one accelerator with a budget of at least the 16 GB floor;
Tier 2 with module residency required for an accelerator host with a budget from
the 6 GB floor up to the 16 GB floor; Tier 1 below the 6 GB floor or without an
accelerator; Tier 0 when torch is absent, on 32-bit ARM, or when reported RAM is
below the 4 GB floor.

The first-run wizard SHALL show the recommendation with its reason and the memory
budget, and SHALL record the matching tier as `[deployment].tier` in the
operator's local configuration only when the operator explicitly confirms. The
tier SHALL be applied as its own configuration layer after the module-selection
profile (the base-thesis `thesis_test` profile by default, or `--profile` /
`KAINE_PROFILE`) and before the operator configuration; the cycle and the
pre-boot check SHALL load configuration in this order, with later layers winning:
shipped `config/kaine.toml`, then the module-selection profile, then the
deployment tier (`KAINE_TIER`, else `[deployment].tier` in
`config/kaine.operator.toml`), then the operator configuration, so recording a
tier never replaces the selected module set.

A tier file SHALL only bound backends and devices; it SHALL NOT enable or disable
modules. A tier file SHALL contain a `[tier]` table; naming a file that lacks one
(for example the module profile `thesis_test`) as the tier via `KAINE_TIER` or
`[deployment].tier` SHALL be refused with a configuration error, and the cycle
and the pre-boot check SHALL exit with `configuration error: ...` instead of a
traceback. A tier file that contains a `[modules]` section or an
`[oscillator].enabled` key SHALL be refused with `ProfileError`. Each tier file
SHALL carry an advisory `[tier]` table with `name`, `unsupported_modules`, and
`oscillator_supported`. The pre-boot check SHALL include a `Tier fit` row: it SHALL
FAIL naming any enabled module in `unsupported_modules` or an enabled oscillator
when `oscillator_supported` is false, with the fix to disable them in the operator
config or record a larger tier; it SHALL PASS when they fit; it SHALL SKIP when
the merged configuration contains no `[tier]` table; and it SHALL FAIL on a
malformed `[tier]` table or malformed `[oscillator]` shape, naming the problem.

#### Scenario: 8 GB unified Jetson
- **WHEN** the host has one unified-memory accelerator and 8 GB of RAM
- **THEN** the recommender proposes Tier 2 with module residency required and does not recommend the CPU-only Tier 1

#### Scenario: Operator declines the recommendation
- **WHEN** the wizard proposes a tier and the operator declines
- **THEN** no tier is written and the existing configuration is unchanged

#### Scenario: Recorded tier keeps the base-thesis modules
- **WHEN** the operator accepts a Tier 2 recommendation and later boots without `--profile` or `KAINE_PROFILE`
- **THEN** the cycle loads the base-thesis module set with the Tier 2 backend settings layered on top (after the module profile and before the operator config), and the pre-boot check validates the same merged configuration

#### Scenario: Tier file with [modules] is refused
- **WHEN** an operator attempts to use a tier file that contains a `[modules]`
  section or `[oscillator].enabled = true`
- **THEN** `ProfileError` is raised and the file is refused, because tiers only
  bound backends and devices and must not toggle modules

#### Scenario: Tier fit fails when tier0 is recorded with topos enabled
- **WHEN** the recorded tier is tier0 and the operator config has `[modules] topos = true`
- **THEN** the pre-boot Tier-fit row FAILS, naming topos as unsupported at tier0
  and advising the operator to disable it or record a larger tier

#### Scenario: Non-tier file named as tier is refused
- **WHEN** `KAINE_TIER` or `[deployment].tier` names a file that does not contain a `[tier]` table (for example the module profile `thesis_test`)
- **THEN** the cycle and the pre-boot check exit with `configuration error: ...` naming the problem instead of a traceback

#### Scenario: Tier fit skips when no tier table is present
- **WHEN** the merged configuration contains no `[tier]` table
- **THEN** the pre-boot Tier-fit row SKIPS

#### Scenario: Tier fit fails on malformed oscillator shape
- **WHEN** the merged configuration contains a `[tier]` table but an `[oscillator]` value is malformed
- **THEN** the pre-boot Tier-fit row FAILS naming the malformed `[oscillator]` shape
