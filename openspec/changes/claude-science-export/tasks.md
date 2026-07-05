# Tasks — Export KAINE research metrics for Claude Science

> **Design-of-record only.** The operator asked to **plan, not implement.** These
> tasks are the future implementation roadmap; do not start them without a go.
> Phases map to `design.md`. **The allowlist, the raw bus archive, and the
> deterministic verdict pipeline are OUT OF SCOPE and MUST NOT be touched** — see C1.

## C0 — Guardrails (read before starting)
- [ ] 0.1 Confirm the change is approved and the operator has resolved the open
      questions in `design.md` §8 (config locus, CSV/JSON default, encrypted-bundle
      handling, attestation persistence, inadmissible-run policy).
- [ ] 0.2 Re-read `design.md` §2/§4: the exporter's ONLY input is a `Bundle`
      produced by `build_research_bundle`; it never reads `data/evaluation/`
      directly and never opens any entity store.

## C1 — DO-NOT-TOUCH boundary (verify, don't modify)
- [ ] 1.1 Confirm `kaine/research/submission.py` is **not** modified: the allowlist
      (`METRICS_ONLY_DIRS`), `DENY_PATTERNS`, and `build_research_bundle` are reused
      verbatim, never copied or widened.
- [ ] 1.2 Confirm `kaine/experiment/*` (admissibility + the authoritative
      PASS/NULL/NEGATIVE verdict producers) is **not** modified — Claude Science is
      exploratory, never a verdict oracle (`design.md` §6).
- [ ] 1.3 Confirm the local-only raw bus archive
      (`state/research/raw_bus_archive/`) and every entity store (Mnemos/Qdrant,
      Eidolon self-model, Lingua intent log/monologue) are **never** referenced by
      the new module.

## C2 — Adapter module (`kaine/research/claude_science_export.py`, new)
- [ ] 2.1 Define `ClaudeScienceProject` dataclass (project_dir, data_files[],
      readme_path, manifest_path, optional plan_path) and
      `export_project(*, bundle: Bundle, out_dir: Path, plan: bool = False)`.
      **Input is a `Bundle` only** — no `eval_root`, no store handle, no bus
      argument (this is what makes it structurally incapable of reading raw data;
      `design.md` §3/§4).
- [ ] 2.2 Reshape each allowlisted metric family present in `bundle.bundle_dir` into
      one analysis-ready `data/<family>.csv` (stable header) plus a pass-through
      `<family>.jsonl` when rows are ragged/nested. No new numbers computed —
      reshape/relabel only.
- [ ] 2.3 Copy `bundle.manifest_path` into the project unchanged (provenance: tier,
      generated-at, included files, admissibility verdict).
- [ ] 2.4 Generate `README.md`: a plain-language data dictionary, one section per
      family (column meanings, units/ranges), stating the data is de-identified
      numeric metrics with no cognitive content, and stating the exploratory-not-
      authoritative boundary (`design.md` §6).
- [ ] 2.5 Optional `plan.json` (when `plan=True`): Claude Science project descriptor
      — title, data-file references, suggested exploratory questions. References and
      prose only; no data values.
- [ ] 2.6 Refuse cleanly on an **encrypted** bundle (write nothing, clear message);
      decrypt-locally-first is an operator step (`design.md` §6 Q3 — confirm the
      resolved option first).
- [ ] 2.7 Source-site comment citing paper §6.7 (allowlist reuse), §4.4/§6.1
      (privacy boundary), and the CAL mental-privacy covenant.

## C3 — Preview (`claude_science_export.py`)
- [ ] 3.1 `preview_project(project) -> str` listing every file to be written and an
      **EXCLUDED** footer naming raw archive, memories, self-model, intent
      log/monologue, and conversation — mirroring `submission.preview`.

## C4 — CLI (`kaine/research/__main__.py`)
- [ ] 4.1 Add `--claude-science` (produce a project folder) alongside `--preview` /
      `--send`; add `--claude-science-out` and a `--plan` flag. Build the bundle via
      the existing `build_research_bundle`, then call `export_project`.
- [ ] 4.2 Print `preview_project` output BEFORE writing; require an explicit
      confirmation to write; EOF/interrupt fails safe (no write), reusing the
      existing confirm/exit-code-2 pattern.
- [ ] 4.3 External-disclosure notice + guardian-consent attestation prompt: state in
      plain language that opening the folder in Claude Science transmits these
      numeric metrics to Anthropic's cloud; record who/when/why into the project
      manifest/README (and audit log per §8 Q4 once resolved).

## C5 — Config (`config/kaine.toml`)
- [ ] 5.1 Add the resolved config block (`design.md` §8 Q1) shipped **disabled**
      (`enabled = false`), with a comment explaining it is an external-disclosure,
      metrics-only, operator-initiated path governed like research submission.

## C6 — Tests (`tests/test_claude_science_export.py`, new)
- [ ] 6.1 **Subset-of-allowlist:** build a bundle from an `eval_root` seeded with all
      `METRICS_ONLY_DIRS` **plus** the standard decoys (`intent_expression`,
      `mnemos_*`, `eidolon_self_model`, `conversation_*`, `replay_*`); export; assert
      every output data-file stem ∈ `METRICS_ONLY_DIRS` and no output path matches any
      `DENY_PATTERNS` substring.
- [ ] 6.2 **Decoys never appear:** assert no decoy filename or content appears
      anywhere under the project (README, manifest, data, plan).
- [ ] 6.3 **Opens no excluded store:** assert `export_project`'s signature accepts no
      `eval_root`/store/bus argument; plant a sensitive file OUTSIDE `bundle_dir` and
      assert the export never reads it (spy/monkeypatch or import-surface check).
- [ ] 6.4 **Encrypted bundle refused, not leaked:** given an encrypted `Bundle`,
      export refuses and writes no plaintext project.
- [ ] 6.5 **Preview + EXCLUDED footer:** `preview_project` lists files and ends with
      the EXCLUDED section.
- [ ] 6.6 **Shipped-config guard:** the new config block ships `enabled = false`
      (mirror `test_shipped_config_research_submission_disabled`).
- [ ] 6.7 **CLI fails safe:** `--claude-science` with EOF at confirm writes nothing
      and returns the no-write exit code.

## C7 — Validation
- [ ] 7.1 `openspec validate claude-science-export --strict` passes.
- [ ] 7.2 Full `kaine.research` + `test_research_submission` suites stay green; no
      `research-submission` test or the allowlist is modified.

## Out of scope (explicit)
- Any network client / API integration or automated opening of the desktop app (no
  public API exists) — the export is a folder opened manually.
- Any "full tier" / cognitive-content Claude Science path — cognitive content never
  gets a cloud route.
- Modifying the allowlist, the raw bus archive, the entity stores, or the
  deterministic verdict pipeline.
- Claude Science's life-science renderers/databases (irrelevant to KAINE metrics).
- The $30k credit-grant program (operator aside only; not a design element).
