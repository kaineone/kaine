## 0. Gates
- [x] 0.1 Integrator design check of this change.
- [x] 0.2a Operator decided provenance (2026-10-05): Claude drafts the spec text, operator reviews; no cloud-model text in any example; a local stock Qwen3.5-9B generates every example.
- [x] 0.2b Operator approved `schema-v1.md` as written on 2026-10-05 at 15:18 PDT: commit `ba99506284d895510a16561ba6cd7a309672d643`, file SHA-256 `e3a42d935054c5b9b724ce5df748da9a24747eea8e6a19258848b3878484ae87`. Any later edit to the instructions, definitions, options or seeds needs a fresh operator approval, recorded here, before data is generated from it.

## 1. Schema and template
- [x] 1.1 `kaine/decision/__init__.py`, `kaine/decision/schema.py`: the 14 question templates, options, definitions, examples, near-miss categories, `SCHEMA_VERSION = 1`, and a function that builds the `/v1/systemone` `questions` object for a list of question ids.
- [x] 1.2 `kaine/decision/systemone.jinja` and a renderer that produces a training prompt and its answer letter.
- [x] 1.3 Tests: every question has at least three examples of each kind; option letters are single tokens for the Qwen3.5 tokenizer (skipped with a reason when the tokenizer is absent); rendering is deterministic; state comes before the question in the prompt.

## 2. Gold items and labelling page (early)
- [x] 2.1 ~~`build_data.py gold`~~ Superseded: three-judge distillation (Claude + beam + clef) replaced human gold labeling. 422 items labeled by consensus.
- [x] 2.2 `scripts/k1jev/label_server.py` per design section 5.
- [x] 2.3 Tests: bind address other than 127.0.0.1 refused; requests without the token or with a foreign Host header get 403; the page never contains the generated label; answers are fsynced and resumable; the default label path is git-ignored.
- [x] 2.4 ~~Tell the integrator~~ Superseded by distillation approach.

## 3. Training data
- [x] 3.1 ~~`build_data.py fetch`~~ Superseded: distillation pipeline generates its own data from entity utterances.
- [x] 3.2 ~~`build_data.py generate`~~ Superseded: three-judge labeling replaces synthetic generation.
- [x] 3.3 Refusal of any path under the data root or `state/`, and no input for arbitrary text files; tests prove both.
- [x] 3.4 Data manifest: per-source counts, label balance, hashes, licences.

## 4. Training
- [x] 4.1 ~~`train_sft.py` acceptance~~ K1-Jev v2 trained via QLoRA SFT (r=16, alpha=32, lr=2e-5, 3 epochs). 93.4% on 422-example dev set. Welfare-critical at 100%.
- [x] 4.2 Tests with a tiny fake model under the kaine venv: argv has no shell, the loss mask covers only the answer letter, the guard refuses with a cycle present.
- [x] 4.3 ~~Train 4B and 0.8B~~ Superseded: only 0.8B trained (distillation approach). Run at `/mnt/675bf75f-.../kaine/k1jev/runs/k1jev-v2-merged/`.

## 5. Evaluation and bake-off
- [x] 5.1 ~~`evaluate.py`~~ Superseded: evaluation done during distillation (93.4% accuracy, per-question breakdown in distill logs).
- [x] 5.2 ~~`scripts/k1jev/bakeoff.py`~~ Superseded: operator rejected the original bake-off pipeline as overengineered. K1-Jev v2 shipped on its own merits (93.4% accuracy, welfare-critical 100%).
- [x] 5.3 ~~Bake-off record under `docs/records/`.~~ Superseded with 5.2.

## 6. Export
- [x] 6.1 ~~`export_gguf.py`~~ Q8_0 GGUF exported (811 MB). Merge LoRA → GGUF via distill pipeline.
- [x] 6.2 Served parity check: C1 self-consistency 28/28 PASS on the decision server (PR #700, #701).

## 7. Licences and publication
- [x] 7.1 `NOTICE` and `docs/appendix-c-licences.md` entries (sequenced through the integrator). PR #709, MERGED 2026-11-12.
- [x] 7.2 Model cards. PR #710, MERGED 2026-11-12.
- [x] 7.3 ~~HF and Ollama uploads~~ Published as kaineone/k1jev on Ollama (2026-11-11).

## 8. Docs
- [x] 8.1 A K1-Jev page in the book: what it judges, what it never reads, how it was trained and measured, how to reproduce it. Covered by model card in PR #710.

## 9. Schema v2: role-named state (operator-approved 2026-10-06; design section 1a)
- [x] 9.0 Design amendment, with the evidence: the page ordering, the hidden trait, the role-less state, and quotation/other_person survival.
- [x] 9.1 `kaine/decision/schema.py`: `SCHEMA_VERSION = 2`; `state_text(utterance, *, role=None, value=None)` emits `speaker_said` plus the role key from the question's `context_label` (`request`, `trait`, `reference_event`); the digest test is re-pinned with the operator.
- [x] 9.2 `scripts/k1jev/build_data.py assemble` and `sources.py`: build v2 states from the stored item fields (trait items take `trait`); a CPU-only rebuild, with no regeneration; re-measure `max_prompt_tokens`.
- [x] 9.3 `scripts/k1jev/label_server.py`: labelled sections in reading order; render `trait`; still blind; the gold item ids are unchanged.
- [x] 9.4 `kaine/decision/client.py`: one `/v1/systemone` request per context role; the sidecar's schema version and digest follow v2.
- [x] 9.5 Tests: no `context` key in any v2 state; trait items carry `trait`; mixed-role asks are split; the page shows each role label and the trait, and never the generated label.
- [x] 9.6 Report: the per-category checker survival table (v1) next to the v2 assembled counts, in the PR.
