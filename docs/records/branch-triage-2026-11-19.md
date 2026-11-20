# Branch triage — 2026-11-19

Scope: 35 remote branches remaining after excluding `origin/main` and `origin/feature/unified-kaine-config*`.
Base for comparison: `origin/main` (`1c01f628` tip as of audit fetch).
"Unique commits" = `git rev-list --count origin/main..branch`. "Unmerged code" is determined by the branch commits not being patch-equivalent to `main` (`git cherry`) and/or the tip introducing files not present (or differing content) on `main`, reconciled against merges already landed in `main`.

| Branch | Unique commits vs main | Last commit date | Change kind | Unmerged code on main? | Recommendation | Notes |
|---|---:|---|---|---|---|---|
| `origin/build/developmental-stimulus` | 16 | 2026-11-01 | code+docs+spec+tools | Yes — 16 novel patches; new files (63) incl. `stimulus_version.py`, band-step tooling | MERGE | Developmental-stimulus progress incl. band-step harness; substantial unmerged work |
| `origin/build/latent-privacy` | 59 | 2026-11-01 | code+spec | Yes — 59 novel patches; 28 new files (companions/volatile bus, latent strip) | ABANDON | Subset of `build/operator-speech`; use latter as canonical |
| `origin/build/operator-speech` | 56 | 2026-11-01 | code+spec+tools | Yes — 56 novel patches; 38 new files incl. operator-speech readout | MERGE | Canonical latent-privacy + operator-speech-as-perception implementation; rebase required |
| `origin/build/welfare-signal-unblended` | 6 | 2026-10-31 | code+docs+spec | Yes — 6 patches; new behaviour + test not on main | MERGE | Welfare signal = own forward-model error; small, self-contained |
| `origin/chore/archive-docs-changes` | 3 | 2026-11-10 | spec (openspec) | No — 2 cherry-equivalent, 1 duplicate | ABANDON | Docs/archive housekeeping already reflected on main |
| `origin/chore/mark-residency-8.3-6.3-8.1-done` | 1 | 2026-11-12 | spec (openspec) | No — only task-status edits, since superseded | ABANDON | Task markers superseded by later `chore: mark residency … done` commits |
| `origin/decision-server/organ-window-test` | 1 | 2026-11-09 | code+tests | No — touched files identical to main | ABANDON | Already integrated (organ window test merged) |
| `origin/decision-server/residency-registration` | 1 | 2026-11-09 | code+config | Yes — task 2.3 registration differs in `footprint.py`/profiles | ABANDON | Decision organ registration already wired in main's `footprint.py`; branch diffs are formatting only |
| `origin/docs/accuracy-pass-2026-10-31` | 2 | 2026-11-10 | docs | Partial — some wording differs | ABANDON | Superseded by `docs: accuracy pass and paper parity (#691)` landed on main |
| `origin/feat/custody-forkmanager-integration` | 5 | 2026-11-11 | code+tests | No — integrated as `feat(custody): ForkManager entity key integration (#714)` | ABANDON | Predecessor branch; work shipped under #714 |
| `origin/feat/individuation-reconstructed-regeneration` | 1 | 2026-11-10 | code | No — integrated as `feat(individuation): reconstructed references … (#689)` | ABANDON | Predecessor branch; work shipped under #689 |
| `origin/feat/novelty-content-fingerprint` | 3 | 2026-10-06 | code+spec | Yes — new unvalidated `measure_novelty.py` + spec | KEEP | Marked `wip … unvalidated`; experimental, retain until validated |
| `origin/feat/qwen3-tts-backend-impl` | 4 | 2026-11-03 | code | No — shipped as `vocal: Qwen3-TTS … (#648/#676/#677)` (evolved) | ABANDON | Predecessor; main's version is newer |
| `origin/feat/residency-12.10-lockstep-docs` | 20 | 2026-11-12 | code+docs | No — all touched files identical to main | ABANDON | Lockstep v1 docs merged via later residency PRs |
| `origin/feat/residency-12.6-entity-clock-lockstep` | 16 | 2026-11-12 | code+tests | Partial — entity-clock lockstep already in main; remaining diffs are style/conflict merges | ABANDON | Lockstep entity clock shipped (`#761`/etc.); branch is stale |
| `origin/feat/residency-12.8-supervisor-barrier` | 17 | 2026-11-12 | code+tests | No — all touched files identical to main | ABANDON | Barrier + boot validation merged |
| `origin/feat/residency-12.9-lockstep-determinism-tests` | 19 | 2026-11-12 | code+tests | No — all touched files identical to main | ABANDON | Determinism tests merged |
| `origin/feat/residency-7.2-auto-rung-selection` | 2 | 2026-11-12 | code+tests | No — all 2 commits patch-equivalent to main | ABANDON | Speech-rung selection shipped (`#761`/`#768`) |
| `origin/feat/stimulus-control-per-pass` | 5 | 2026-11-07 | code+spec | Partial — only `programme_end.py` differs; version returns `None` instead of stop callback | ABANDON | Main retains stop-callback semantics; branch is an older simplification |
| `origin/fix/welfare-freeze-followups` | 8 | 2026-10-30 | code+spec+tests | Yes — fail-safe record/notify/retry not on main | CHERRY-PICK | Main has end-hook fallback (#619/#627); port the 4 newer fail-safe commits |
| `origin/individuation-rebuild/disclosure-test` | 1 | 2026-11-09 | spec (openspec) | No — checkbox state already on main | ABANDON | Cosmetic task-status flip already applied |
| `origin/openspec/residency-d2-d3-d5` | 2 | 2026-10-05 | spec (openspec) | No — amendments already in main's `module-residency-and-speech-tiers` | ABANDON | Superseded by integrated residency amendments |
| `origin/organ/pair-builder-fix` | 17 | 2026-10-31 | code+tests+spec | Yes — new tests (`test_peft_disable_adapter_real.py`, `test_staged_adapter_promotion.py`) not on main | ABANDON | Exact duplicate tip of `organ/self-denial-ablation-v2`; drop this name, keep the latter |
| `origin/organ/self-denial-ablation-v2` | 17 | 2026-10-31 | code+tests+spec | Yes — new tests not on main | KEEP | Research/experimental feature; differs from shipped #629 |
| `origin/research/band-step-check` | 15 | 2026-10-31 | tooling+spec+docs | Yes — new tools/research scripts and band-step records | KEEP | Research instrumentation; unmerged by design |
| `origin/social-cognition-identity` | 3 | 2026-11-10 | spec (openspec) | No — archived on main (`2026-11-10-social-cognition-identity`) | ABANDON | Spec work archived; branch superseded |
| `origin/spec/agency-learning-metacognition-2026-10-31` | 1 | 2026-10-31 | spec (openspec) | Yes — 5 of 6 proposed changes absent on main | KEEP | Design-only specs (agency/learning/metacognition) not implemented |
| `origin/spec/content-code-2026-10-31` | 10 | 2026-11-01 | spec (openspec) | Partial — 3 implemented, 4 missing (incl. heard-text volatile bus, operator-speech, welfare-signal, workspace-content-code) | CHERRY-PICK | Port only the missing change folders if still needed; do not merge whole branch |
| `origin/spec/conversation-memory-2026-11-01` | 4 | 2026-11-01 | spec (openspec) | Yes — `conversation-memory` change absent on main | KEEP | Design-only (episodic-recall-content exists on main) |
| `origin/spec/development-run-2026-10-31` | 3 | 2026-11-01 | spec (openspec) | No — archived on main (`2026-11-04-study-to-development-run`) | ABANDON | Fully integrated into archived change |
| `origin/spec/grounding-social-safety-2026-10-31` | 4 | 2026-10-31 | spec (openspec) | Yes — none of 8 proposed changes present on main | KEEP | Unimplemented design; retain until scoped |
| `origin/spec/latent-workspace-memory-2026-10-31` | 5 | 2026-10-31 | spec (openspec) | Yes — 3 of 4 memory changes absent on main | KEEP | Partially implemented (episodic-recall exists); keep remainder |
| `origin/spec/pre-study-gates-2026-10-31` | 17 | 2026-11-01 | spec (openspec) | Yes — 4 of 7 proposed changes absent on main | KEEP | Design work partially absorbed; retain unimplemented parts |
| `origin/spec/sensors-bodies-locus-2026-11-01` | 10 | 2026-11-01 | spec (openspec) | Yes — all 3 changes absent on main | KEEP | Body/locus/place theory design not implemented |
| `origin/tools/crossmodal-decodability` | 1 | 2026-10-31 | code+tests | No — both touched files identical to main | ABANDON | Measurement tool already merged |
