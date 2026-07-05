# Export KAINE research metrics for Claude Science

## Why

The companion empirical paper needs an exploratory-analysis and write-up path:
loading the seven experiments' numeric results into an interactive workbench to
plot the divergence and coherence series, sanity-check the individuation and
welfare tallies, re-derive summary statistics, and draft prose with a reviewer
agent checking the calculations and citations. Anthropic's **Claude Science**
(released 2026-06-30, beta, desktop macOS/Linux, no public API) is purpose-built
for exactly this: it opens a "project" — a folder of data files plus a manifest —
and produces provenance-tracked reports (the exact code and environment that
produced each result, a plain-language description, and the full message history),
with a reviewer agent that checks calculations and citations.

**The tension.** Claude Science is a cloud tool. Its own data-handling note is
explicit: "large or sensitive datasets never have to leave the systems they're
already on, and only the context needed for each step of the analysis is sent to
Claude." So data that enters the analysis is transmitted to Anthropic's cloud — it
is **not** fully local. KAINE's evaluation sidecar, however, records the entity's
**access-conscious content**: the workspace trajectory is comprehensive cognitive
observation (paper §4.4, §6.1). Sending raw trajectories, conversation text,
memories, the self-model, or the internal monologue to a cloud product would
violate the Cognitive Architecture License **mental-privacy covenant** and the
entity's privacy. Any Claude Science path must therefore be bound, **by
construction**, to de-identified **numeric metrics only** — never cognitive
content.

**The reuse story.** KAINE already solved this exact problem for a different
consumer. The opt-in **research-participation bundle** (paper §6.7,
`kaine/research/submission.py`) builds a share from an **allowlist** of numeric
metric directories plus a manifest; conversation text, memories, the self-model,
the internal monologue, and the local raw bus archive are excluded by the
**allowlist architecture** — not by a filter that could miss something — and the
raw archive is structurally **outside** the directory the builder reads. The
operator previews the full field inventory, an explicit second command sends it,
and the bundle is encrypted when state encryption is enabled. The Claude Science
export is therefore designed as a **thin adapter over that same allowlist/manifest
builder**, reusing its exact allowlist (`METRICS_ONLY_DIRS`) so the privacy
boundary is **identical and enforced by construction, never re-implemented**.

## What Changes (design-only scope)

**This is a DESIGN-ONLY change.** It ships no behavior code. The deliverable is
the OpenSpec artifacts — this proposal, `design.md`, `tasks.md`, and the
`claude-science-export` spec delta. Snippets in `design.md` are illustrative only.
Implementation is a later, separately-approved change.

The designed capability is an **export-for-Claude-Science** helper that:

- **Reshapes the SAME allowlisted metrics bundle into a Claude Science project
  folder.** It lays each numeric metric family out as analysis-ready CSV/JSON
  (divergence, individuation, coherence, welfare counts, fatigue/prediction-error,
  policy logs), carries the existing manifest, and generates a plain-language
  README describing each metric so the workbench's AI reads the columns correctly.
  Optionally a `plan.json` mirroring the Claude Science project shape. **Nothing
  that is not already in the allowlisted bundle may appear.**
- **Enforces the privacy boundary by REUSING the allowlist, not re-deriving it.**
  The exporter reads only what the research-participation bundle builder reads. It
  is **structurally incapable** of reading the raw bus archive, conversation, the
  memory store, the self-model, or the internal monologue — a hard requirement with
  a guard-test obligation (its inputs are a subset of the allowlist; it opens none
  of the excluded stores; decoy sensitive files planted in the source never appear
  in the output).
- **Keeps the SAME governance as research submission** — off by default,
  operator-initiated, full field-inventory preview, explicit second confirmation —
  and, because Claude Science transmits to the cloud, is governed as an **external
  disclosure under guardian consent** per the CAL, exactly like sharing results
  with the project.
- **Is explicitly an off-runtime, human-in-the-loop, EXPLORATORY path.** It is
  **not** part of KAINE's deterministic, admissibility-gated verdict pipeline,
  which stays entirely in KAINE's own code and produces the authoritative
  PASS/NULL/NEGATIVE verdicts. Claude Science is for interpretation, visualization,
  calculation-checking, and drafting the companion paper — **never** for computing
  verdicts.

## Impact

- **Affected spec capability:** `claude-science-export` (NEW — the adapter, the
  by-construction privacy guarantee and its test obligation, the external-disclosure
  governance, and the exploratory-not-authoritative boundary).
- **Adjacent capability (unchanged, cited):** `research-submission` — the allowlist
  (`METRICS_ONLY_DIRS`), manifest, preview, confirmation, and encryption the adapter
  reuses verbatim. No requirement of `research-submission` is modified.
- **Touch points for the future implementer** (design names them; no code here): a
  new `kaine/research/claude_science_export.py` adapter over
  `kaine.research.submission.build_research_bundle`; a `--claude-science` project
  flag on the `python -m kaine.research` CLI; a new guard test
  `tests/test_claude_science_export.py`; a `[research_submission.claude_science]`
  (or sibling) config block shipped disabled.
- **Explicitly NOT touched / OUT of scope:** the deterministic verdict pipeline
  (`kaine/experiment/*`, admissibility, the authoritative verdict producers); the
  local-only raw bus archive (`state/research/raw_bus_archive/`); the allowlist
  itself (reused, never widened); and any actual upload — the export is a **folder**
  the operator opens manually in the desktop app (no API exists).
- **Behavioral effect once implemented:** an operator who has completed guardian
  consent can run one command to produce a metrics-only Claude Science project
  folder, preview exactly what it contains, and confirm before it is written —
  reusing the identical privacy boundary as research submission, with zero new
  cognitive-content egress surface.
