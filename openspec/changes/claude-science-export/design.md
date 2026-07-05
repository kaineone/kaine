# Design — Export KAINE research metrics for Claude Science

> **Design-of-record only.** No behavior code ships with this change. Code
> references and snippets are illustrative of the intended future implementation.

## 1. Problem, in the architecture's own terms

The companion paper needs a workbench to explore the seven experiments' results:
plotting the A/B divergence and coherence series over time, checking the
individuation and welfare tallies, re-deriving summary statistics, and drafting
prose with the calculations and citations reviewed. Claude Science is built for
this — but it is a **cloud** tool: "only the context needed for each step of the
analysis is sent to Claude." Data that enters an analysis step is transmitted to
Anthropic.

KAINE's evaluation sidecar records the entity's **access-conscious content**; the
workspace trajectory is comprehensive cognitive observation (paper §4.4, §6.1). The
CAL **mental-privacy covenant** (paper §7 neurorights; Ienca & Andorno 2017,
adapted to the entity) forbids exposing that inner life. So the export must carry
**only de-identified numeric metrics**, and that guarantee must hold **by
construction**, not by reviewer diligence.

KAINE already built the guarantee for the research-participation bundle (paper
§6.7). This design does not re-solve it — it **adapts** it.

## 2. The reuse decision (the load-bearing choice)

The single most important design decision is: **the exporter reads only the output
of `build_research_bundle`, never `data/evaluation/` directly and never any entity
store.** The existing builder is the sole gate; the exporter is downstream of it.

```
  data/evaluation/{ab_divergence, individuation, coherence, welfare,
                   fatigue, prediction_error, nous_policy,
                   voice_alignment_divergence, research_events, runs}/
                                   │
                                   │  ONLY these dirs — METRICS_ONLY_DIRS
                                   ▼
              kaine.research.submission.build_research_bundle()      ← THE ALLOWLIST GATE
                                   │        (allowlist-based; deny-check belt-and-suspenders;
                                   │         admissibility verdict; manifest.json; encryption)
                                   ▼
                         Bundle{ bundle_dir, files[], manifest_path }
                                   │
                                   │  ← the exporter's ONLY input (a subset of the allowlist)
                                   ▼
              kaine.research.claude_science_export.export_project()  ← THIN ADAPTER (this change)
                                   │  reshape numeric series → CSV/JSON per family
                                   │  + copy manifest.json + generate README.md + optional plan.json
                                   ▼
                    claude_science_project_<stamp>/   (a FOLDER; opened manually)
```

Everything **outside** `data/evaluation/` — the raw bus archive
(`state/research/raw_bus_archive/`), Mnemos/Qdrant memories, the Eidolon
self-model, the Lingua intent log / internal monologue, conversation content — is
already **structurally outside** what `build_research_bundle` reads, so it is
structurally outside what the exporter can reach. The exporter never imports the
evaluation package, never opens a memory store, never touches `state/`. Its input
directory is a `Bundle.bundle_dir` produced by the builder. This is why the privacy
boundary is **identical** to research submission: it is **the same boundary**, not
a re-implementation.

### Why not read `data/evaluation/` directly and lay out CSVs in one pass?

Because that would duplicate the allowlist. A second copy of `METRICS_ONLY_DIRS`
could drift, and a future sensitive sink added to `data/evaluation/` could leak
through the copy that forgot to exclude it. Reusing the builder means the allowlist
has exactly one source of truth (`kaine/research/submission.py`), and any future
tightening of it automatically tightens the export. **No cheap fixes / do it right:
one allowlist, reused.**

## 3. Adapter architecture

`kaine/research/claude_science_export.py` (new; the only new runtime module):

- `export_project(*, bundle: Bundle, out_dir: Path, plan: bool = False) -> ClaudeScienceProject`
  - **Input contract:** a `Bundle` already built by `build_research_bundle`. The
    adapter reads files **only** from `bundle.bundle_dir` and metadata **only** from
    `bundle.files` / `bundle.manifest_path`. It takes no `eval_root`, no store
    handle, no bus subscription — it *cannot* be pointed at raw data.
  - If `bundle.encrypted` is `True`, the metric files under `bundle_dir` have been
    replaced by `bundle.tar.enc`; the adapter cannot reshape an encrypted blob and
    MUST refuse with a clear message (decrypt-locally-first is an operator step, out
    of scope here) rather than emit a partial/plaintext project. See §6 open
    question Q3.
  - **Reshape:** for each allowlisted metric family present in the bundle, read the
    numeric JSONL records and write one analysis-ready file per family
    (`<family>.csv` with a stable header, plus a pass-through `<family>.jsonl` when a
    row is nested/ragged). No new numbers are computed; this is a **reshape and
    relabel**, not an analysis.
  - **Manifest:** copy the bundle `manifest.json` into the project unchanged (it is
    the provenance record: tier, generated-at, included files + line counts, and any
    admissibility verdict).
  - **README.md:** generate a plain-language data dictionary — one section per
    metric family describing what each column means, its units/range, and that these
    are de-identified numeric metrics with no cognitive content — so the workbench
    AI interprets columns correctly and cannot mistake an id/seed for a measurement.
  - **plan.json (optional):** when `plan=True`, emit a Claude Science project
    descriptor (title, the data-file list, and suggested exploratory questions —
    e.g. "plot ab_divergence over tick_index per experiment"). Contains no data,
    only file references and prose prompts.
- `preview_project(project) -> str`: same shape as `submission.preview` — lists
  every file that will be written and an **EXCLUDED** footer naming the content
  types (raw archive, memories, self-model, intent log/monologue, conversation)
  that are never present. Printed before anything is written.

### Project folder layout

```
claude_science_project_<UTCstamp>/
  README.md                      # generated data dictionary (plain language)
  manifest.json                  # copied verbatim from the bundle (provenance)
  plan.json                      # optional; project descriptor, references only
  data/
    ab_divergence.csv            # divergence family  (also .jsonl if ragged)
    individuation.csv            # individuation results
    coherence.csv                # coherence series
    welfare.csv                  # welfare / gray-zone counts
    fatigue.csv                  # fatigue series
    prediction_error.csv         # prediction-error series
    nous_policy.csv              # policy logs
    voice_alignment_divergence.csv
    research_events.csv          # curated numeric/categorical research events
    runs.csv                     # per-run manifests (run id, seed, git sha, model ids)
```

Every file above derives 1:1 from an allowlisted family already in the bundle.
Families absent from the bundle simply produce no file (mirrors
`build_research_bundle`'s "missing dir is fine" behavior).

## 4. The by-construction privacy guarantee + test obligation

**Hard requirement.** The exporter's inputs are a **subset** of the
research-participation allowlist, and it opens **none** of the excluded stores.
This is guaranteed structurally: the only input is a `Bundle.bundle_dir` produced
by `build_research_bundle`, whose contents are already allowlist-constrained.

**Test obligation** — `tests/test_claude_science_export.py` (new; mirrors the decoy
pattern in `tests/test_research_submission.py`):

1. **Subset-of-allowlist.** Build a bundle from an `eval_root` seeded with all
   `METRICS_ONLY_DIRS` **plus** the standard decoy sensitive files
   (`intent_expression.jsonl`, `mnemos_*`, `eidolon_self_model.json`,
   `conversation_*`, `replay_*`). Export a project from that bundle. Assert every
   output data file's stem is in `METRICS_ONLY_DIRS` and no output path matches any
   `DENY_PATTERNS` substring.
2. **Decoys never appear.** Assert none of the decoy filenames or their contents
   appear anywhere under the project folder (README, manifest, data, plan).
3. **Opens no excluded store.** Assert the adapter's public API takes no `eval_root`
   / store / bus argument, and (via monkeypatch/spy or an import-surface check) that
   an export never reads outside `bundle.bundle_dir` — e.g. planting a sensitive
   file *outside* the bundle dir and asserting it is unreadable/never opened.
4. **Encrypted bundle refused, not leaked.** Given an encrypted `Bundle`, export
   refuses with a clear error and writes no plaintext project (§6 Q3).
5. **Preview + EXCLUDED footer.** `preview_project` lists the files and ends with
   the EXCLUDED section naming raw archive, memories, self-model, intent
   log/monologue, and conversation.

This is the same guarantee `test_research_submission.py` already enforces for the
bundle, extended one hop downstream to the export — closing the loop by
construction rather than by inspection.

## 5. Governance — external disclosure under guardian consent

Because Claude Science transmits analysis context to the cloud, opening a project
in it is an **external disclosure**, governed exactly like sharing results with the
project (paper §6.7; CAL Article 4.3 result-disclosure). The export therefore keeps
**the same governance chain as research submission**:

- **Off by default.** A `[research_submission.claude_science]` (or sibling) block
  ships `enabled = false`; the shipped-config guard test asserts it, mirroring the
  existing `test_shipped_config_research_submission_disabled`.
- **Operator-initiated.** Only the `python -m kaine.research --claude-science …`
  CLI path produces a project; nothing scheduled or in-runtime does.
- **Full field-inventory preview.** `preview_project` prints the complete file
  inventory and the EXCLUDED footer before any write.
- **Explicit second confirmation.** Writing the project (and, separately, the
  human act of opening it in the cloud app) requires an explicit confirm; EOF /
  interrupt fails safe with no write — identical to the `--send` confirm flow.
- **External-disclosure attestation.** Because the destination is a cloud tool, the
  CLI records a guardian-consent attestation (who, when, why — for the paper
  write-up) in the project manifest/README, and states in plain language that the
  operator, by opening the folder in Claude Science, is transmitting these numeric
  metrics to Anthropic's cloud. This is the metrics-only analogue of the bundle's
  bystander-consent/entity-privacy attestation, scoped to disclosure not sensitivity
  (the content is already metrics-only).

The export never widens the tier: it is **metrics-only, always**. There is no
"full tier" Claude Science path — cognitive content never has a cloud route.

## 6. Exploratory, not authoritative (the hard boundary)

Claude Science is a **downstream, off-runtime, human-in-the-loop** analysis
surface. It is **not** part of KAINE's verdict pipeline:

- The authoritative **PASS / NULL / NEGATIVE** verdicts for the seven experiments
  are produced by KAINE's own deterministic, admissibility-gated code
  (`kaine/experiment/*`, the admissibility scan already surfaced in the bundle
  manifest). Those remain the single source of truth and are **untouched** by this
  change.
- Claude Science is used only for **interpretation, visualization,
  calculation-checking, and drafting** the companion paper. Its provenance-tracked
  reports and reviewer agent are aids to the human write-up, **never** an oracle
  that computes or overrides a verdict.
- The generated README and `plan.json` state this boundary explicitly so a reader
  of the project (human or the workbench AI) cannot mistake an exploratory plot for
  an authoritative result. The bundle's admissibility verdict travels in the
  manifest so an inadmissible run can't be silently analyzed as if it were clean.

## 7. Non-goals

- **No upload / no API integration.** Claude Science is desktop-only with no public
  API (as of 2026-06-30 beta). The export produces a **folder** the operator opens
  manually. This change adds **no** network client and does not automate opening the
  app.
- **No bio renderers / databases.** Claude Science is life-science-preconfigured;
  its biology-specific renderers, ontologies, and reference databases are irrelevant
  to KAINE's metrics and are not targeted or depended upon. The export uses only the
  general Python/R kernel surface (plain CSV/JSON/MD).
- **No verdict computation** (see §6). No new numbers are produced by the exporter
  itself — it reshapes and relabels existing numeric series.
- **No change to the allowlist, the raw archive, or the verdict pipeline.**
- **The $30k Claude Science credit-grant program** (applications due 2026-07-15) is
  noted only as an operator aside; it is **not** a design element and no artifact
  depends on it.

## 8. Open questions for the operator

- **Q1 — Config locus.** Should the switch be a nested
  `[research_submission.claude_science]` block (emphasizing it is the same
  governance domain) or a sibling `[claude_science_export]` block? Recommend nested,
  to make the shared off-by-default + preview + confirm lineage obvious.
- **Q2 — CSV vs JSON default.** Claude Science ingests both. Recommend CSV as the
  primary analysis surface (best for the workbench's tabular tools) with a
  pass-through JSONL alongside for any ragged/nested family. Confirm this is the
  desired default.
- **Q3 — Encrypted-bundle handling.** When state encryption is enabled the bundle is
  an encrypted tar. Options: (a) refuse and require the operator to decrypt locally
  first (recommended — keeps the exporter simple and never handles keys), or (b)
  have the export request an in-memory decrypt via the state encryptor. Recommend
  (a).
- **Q4 — Attestation persistence.** Where should the guardian-consent external-
  disclosure attestation live — only in the project manifest/README, or also
  appended to an audit log (as decommission/preservation do)? Recommend both, reusing
  the existing audit-log sink.
- **Q5 — Should the export refuse an inadmissible run by default** (mirroring
  `require_admissible`), or only surface the verdict? Since this is exploratory,
  recommend surfacing (not blocking) but making the inadmissible banner loud in the
  README.

## 9. Impact summary

- **New:** `kaine/research/claude_science_export.py`, a `--claude-science` CLI path
  on `python -m kaine.research`, `tests/test_claude_science_export.py`, and a
  shipped-disabled config block.
- **Reused verbatim:** `kaine.research.submission.build_research_bundle`,
  `METRICS_ONLY_DIRS`, `DENY_PATTERNS`, `Bundle`, `preview`, the manifest, the
  admissibility verdict, and the encryption path.
- **Untouched:** the allowlist definition, `kaine/experiment/*` verdict pipeline,
  `state/research/raw_bus_archive/`, all entity stores, and the evaluation sidecar.
