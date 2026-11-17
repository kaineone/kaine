# Design

Status: PARKED (roadmap item, not active work)

## Context

KAINE's config lives in `config/kaine.toml` (shipped, all-off defaults) with
`config/kaine.operator.toml` (gitignored operator overrides) merged on top. Secrets
go in `config/secrets.toml` or environment variables. The first-run wizard writes the
operator override. Tier profiles under `config/profiles/` preset groups of values for
different hardware.

The shipped TOML has inline comments for most sections, but there is no guarantee of
completeness: modules can read keys that the shipped file does not mention, and some
defaults are coded in Python rather than declared in TOML. The wizard covers the most
important knobs but not all of them.

## Goals / Non-Goals

**Goals:**

- Every config key has a single source of truth for its default, type, bounds, tier,
  and explanation.
- An operator can read one reference file and understand every knob without searching
  the source.
- A validation command catches typos, unknown keys, and out-of-range values before
  boot.
- The wizard and the questionnaire stay in sync with the reference automatically.

**Non-Goals:**

- Changing the config file format (TOML stays).
- Changing the merge order (shipped, operator override, secrets, env vars).
- Building a GUI or web-based config editor (future work).
- Auto-generating config from hardware detection (the wizard already does this; this
  change documents the result, it doesn't replace the detection).

## Decisions

**D1: Reference file, not a schema language.** The reference is a commented TOML file
(`config/kaine.reference.toml`) rather than a JSON Schema or a custom DSL. Operators
already know TOML. The reference looks like a real config file; they copy sections
from it. The tier and bounds metadata go in structured comments that the validator
parses (e.g., `# tier: basic  bounds: 0.1..100.0`).

Alternative considered: a Python dataclass registry with auto-generated TOML. Rejected
because it adds a build step and moves the documentation away from the file operators
actually read.

**D2: Generated, then hand-edited.** A script reads `list_all_defaults()` and emits
the reference skeleton. Inline explanations are hand-written. The CI check verifies
keys and defaults match, but does not overwrite the explanations. This avoids stale
docs while keeping human-quality writing.

**D3: Tiers are advisory, not enforced.** The tiers (`basic`, `standard`, `advanced`)
control which keys the wizard and questionnaire present. They do not prevent an
operator from setting any key in their override file.

**D4: Validation is offline only.** The validation command runs before boot, not at
boot. Boot does not reject unknown keys (backward compatibility with older configs).
The pre-boot check row for config validation is a recommendation, not a gate.

## Risks / Trade-offs

**Maintenance cost.** Every new config key needs a reference entry and an explanation.
The CI sync check catches missing keys, but the explanation still requires a human.
Mitigant: the generator emits a placeholder comment that fails a lint check until
replaced.

**Comment-based metadata is fragile.** Parsing `# tier: basic  bounds: 0.1..100.0`
from TOML comments is less robust than a typed schema. Mitigant: the parser is simple
(regex on `# tier:` and `# bounds:`), and a test validates every reference entry
parses correctly.

**Wizard sync.** Keeping the wizard's question set in lockstep with the reference
requires a test that reads both. If the wizard adds a question that the reference
doesn't know about, or vice versa, the test fails.
