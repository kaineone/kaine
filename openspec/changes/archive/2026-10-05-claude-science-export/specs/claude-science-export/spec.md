# claude-science-export (new capability — DESIGN ONLY)

## ADDED Requirements

### Requirement: The export reuses the research-participation allowlist by construction

The Claude Science export SHALL be a thin adapter over the existing
research-participation bundle builder (`kaine.research.submission.build_research_bundle`)
and SHALL read its data **only** from a `Bundle` that builder produced. The
exporter SHALL NOT read `data/evaluation/` directly, SHALL NOT re-declare or widen
the allowlist (`METRICS_ONLY_DIRS`), and SHALL take no `eval_root`, memory-store,
self-model, intent-log, raw-archive, or event-bus input. Every file the export
writes SHALL derive from a metric family already present in the allowlisted bundle,
and SHALL NOT introduce any content that is not already in that bundle. Because the
raw bus archive, memories, the self-model, the internal monologue, and conversation
content are structurally outside what the bundle builder reads, they SHALL be
structurally unreachable by the exporter.

#### Scenario: Exporter input is a subset of the allowlist

- **WHEN** an export project is produced from a bundle built from an evaluation root
  that also contains decoy sensitive files (intent log, memories, self-model,
  conversation, replay)
- **THEN** every output data file corresponds to an allowlisted metric family, no
  output path matches any denied pattern, and none of the decoy filenames or their
  contents appear anywhere in the project folder

#### Scenario: Exporter cannot be pointed at raw data

- **WHEN** the exporter's public interface is inspected
- **THEN** it accepts only a builder-produced bundle and an output directory, with
  no parameter that would let it read an evaluation root, a memory store, the
  self-model, the intent log, the raw bus archive, or the event bus

### Requirement: The export produces a metrics-only Claude Science project folder

The export SHALL lay the allowlisted numeric metrics out as analysis-ready files —
one per metric family (divergence, individuation, coherence, welfare counts,
fatigue, prediction-error, policy logs, and any other allowlisted family present) —
alongside the bundle's existing manifest and a generated plain-language README that
describes each metric so a workbench can interpret the columns correctly. It MAY
also emit an optional project descriptor that references the data files and
suggested exploratory questions. The export SHALL NOT compute or alter any metric
value; it SHALL only reshape and relabel existing numeric series. The export SHALL
remain metrics-only always; there SHALL be no higher-sensitivity or cognitive-content
Claude Science export tier.

#### Scenario: Project folder contains only reshaped allowlisted metrics plus manifest and README

- **WHEN** an export project is produced from a metrics bundle
- **THEN** the folder contains a data file per allowlisted family present in the
  bundle, the bundle manifest copied unchanged, and a generated README, and contains
  no cognitive content

#### Scenario: No cognitive-content tier exists

- **WHEN** any operator invokes the export with any flag
- **THEN** the produced project contains only de-identified numeric metrics and
  there is no option that adds transcripts, memories, the self-model, the internal
  monologue, or conversation content

### Requirement: The export is off by default, previewed, and confirmed

The export SHALL be disabled by default in shipped configuration and SHALL never run
automatically or in-runtime. It SHALL be operator-initiated via the research CLI,
SHALL present a full field-inventory preview — listing every file to be written and
an explicit EXCLUDED section naming the raw archive, memories, self-model, intent
log/monologue, and conversation — before writing anything, and SHALL require an
explicit confirmation to write the project. An end-of-input or interrupt at the
confirmation SHALL fail safe with nothing written.

#### Scenario: Disabled and inert by default

- **WHEN** the shipped configuration is loaded
- **THEN** the Claude Science export is disabled and nothing is produced without an
  explicit operator invocation

#### Scenario: Preview precedes any write

- **WHEN** the operator invokes the export
- **THEN** the full file inventory and the EXCLUDED section are shown before any file
  is written, and an explicit confirmation is required

#### Scenario: Fail-safe on end-of-input

- **WHEN** the confirmation prompt receives end-of-input or an interrupt
- **THEN** no project folder is written and the command exits without producing an
  artifact

### Requirement: The export is governed as an external disclosure under guardian consent

The export SHALL be governed as an external disclosure under guardian consent per
the license, in the same manner as sharing results with the project, because opening
a project in Claude Science transmits analysis context to a cloud service. The
export SHALL state in plain language that opening the folder in Claude Science
transmits the numeric metrics to a cloud service, and SHALL record a guardian-consent
attestation with the project. When the source bundle is encrypted, the export SHALL
refuse to write a plaintext project rather than silently downgrade the protection.

#### Scenario: External-disclosure notice and attestation are recorded

- **WHEN** an export project is produced
- **THEN** the project records that opening it in the cloud tool transmits these
  numeric metrics externally, together with a guardian-consent attestation

#### Scenario: Encrypted bundle is not silently downgraded

- **WHEN** the export is invoked on an encrypted bundle
- **THEN** it refuses with a clear message and writes no plaintext project

### Requirement: The export is exploratory and never authoritative

The export SHALL be an off-runtime, human-in-the-loop, exploratory analysis path for
interpretation, visualization, calculation-checking, and drafting the companion
paper only. It SHALL NOT be part of the deterministic, admissibility-gated verdict
pipeline, and SHALL NOT compute, replace, or override the authoritative
PASS/NULL/NEGATIVE verdicts, which remain produced solely by the system's own code.
The generated project SHALL state this exploratory-not-authoritative boundary, and
the bundle's admissibility verdict SHALL travel in the manifest so an inadmissible
run cannot be analyzed as if it were clean.

#### Scenario: Verdict pipeline is untouched

- **WHEN** an export project is produced and analyzed in the cloud tool
- **THEN** the authoritative experiment verdicts are unchanged and still come only
  from the system's own deterministic pipeline

#### Scenario: Admissibility verdict travels with the export

- **WHEN** the source bundle carries an admissibility verdict
- **THEN** that verdict is present in the exported manifest and the exploratory-not-
  authoritative boundary is stated in the project
