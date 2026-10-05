## 0. Gates
- [ ] 0.1 Integrator design check of this change.
- [x] 0.2a Operator decided provenance (2026-10-05): Claude drafts the spec text, operator reviews; no cloud-model text in any example; a local stock Qwen3.5-9B generates every example.
- [x] 0.2b Operator approved `schema-v1.md` as written on 2026-10-05 at 15:18 PDT: commit `ba99506284d895510a16561ba6cd7a309672d643`, file SHA-256 `e3a42d935054c5b9b724ce5df748da9a24747eea8e6a19258848b3878484ae87`. Any later edit to the instructions, definitions, options or seeds needs a fresh operator approval, recorded here, before data is generated from it.

## 1. Schema and template
- [x] 1.1 `kaine/decision/__init__.py`, `kaine/decision/schema.py`: the 14 question templates, options, definitions, examples, near-miss categories, `SCHEMA_VERSION = 1`, and a function that builds the `/v1/systemone` `questions` object for a list of question ids.
- [x] 1.2 `kaine/decision/systemone.jinja` and a renderer that produces a training prompt and its answer letter.
- [x] 1.3 Tests: every question has at least three examples of each kind; option letters are single tokens for the Qwen3.5 tokenizer (skipped with a reason when the tokenizer is absent); rendering is deterministic; state comes before the question in the prompt.

## 2. Gold items and labelling page (early)
- [ ] 2.1 `scripts/k1jev/build_data.py gold`: about 420 items from a separate generation run, near-miss share of at least 40% per question, written outside the repository.
- [x] 2.2 `scripts/k1jev/label_server.py` per design section 5.
- [x] 2.3 Tests: bind address other than 127.0.0.1 refused; requests without the token or with a foreign Host header get 403; the page never contains the generated label; answers are fsynced and resumable; the default label path is git-ignored.
- [ ] 2.4 Tell the integrator the page is ready, with the item count, so the operator can be scheduled.

## 3. Training data
- [ ] 3.1 `build_data.py fetch`: Banking77 CSVs at a pinned commit (SHA-256 checked) and MultiNLI parquet at the pinned revision, fiction genre dropped.
- [ ] 3.2 `build_data.py generate`: synthetic train and dev through a temporary local llama-server under the GPU lock, with the rule filter and the second-pass label check. The generator's Qwen3.5-9B weights are fetched at setup time at a pinned revision and get a NOTICE entry (7.1).
- [ ] 3.3 Refusal of any path under the data root or `state/`, and no input for arbitrary text files; tests prove both.
- [ ] 3.4 Data manifest: per-source counts, label balance, hashes, licences.

## 4. Training
- [ ] 4.1 `scripts/k1jev/train_sft.py` per design section 6, with the running-cycle guard.
- [ ] 4.2 Tests with a tiny fake model under the kaine venv: argv has no shell, the loss mask covers only the answer letter, the guard refuses with a cycle present.
- [ ] 4.3 Train 4B and 0.8B, in GPU chunks of at most 2 hours with a gap between chunks so the Qwen review queue can drain. Each chunk is announced to the integrator before the lock is taken. Order:
  - W1: synthetic data generation (local Qwen3.5-9B llama-server, stopped the moment the window ends), about 2 h; gold generation is a short slice of it.
  - W2a: train 0.8B, then start 4B (checkpointing every 30 min).
  - W2b: finish 4B from its checkpoint.
  - W2c: fine-tune the deberta-v3-large and GLiClass controls.
  - W2d: bake-off inference on gold for every system, then the export parity check.

## 5. Evaluation and bake-off
- [ ] 5.1 `scripts/k1jev/evaluate.py`: temperature fit, thresholds, gold metrics with intervals and ECE.
- [ ] 5.2 `scripts/k1jev/bakeoff.py`: the zero-shot decision models, the two fine-tuned encoder controls and the deterministic graders, on gold.
- [ ] 5.3 Bake-off record under `docs/records/`.

## 6. Export
- [ ] 6.1 `scripts/k1jev/export_gguf.py`: convert, metadata, quantize, threshold sidecar.
- [ ] 6.2 Served parity check (design section 7) on the real llama-server.

## 7. Licences and publication
- [ ] 7.1 `NOTICE` and `docs/appendix-c-licences.md` entries (sequenced through the integrator).
- [ ] 7.2 Model cards.
- [ ] 7.3 HF and Ollama uploads, each confirmed with the integrator immediately before.

## 8. Docs
- [ ] 8.1 A K1-Jev page in the book: what it judges, what it never reads, how it was trained and measured, how to reproduce it.
