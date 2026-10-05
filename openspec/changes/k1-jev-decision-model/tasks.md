## 0. Gates
- [ ] 0.1 Integrator design check of this change.
- [ ] 0.2 Operator confirms the provenance rule (design section 3) and reviews `schema.py`'s instructions, definitions and seed examples before the first data build.

## 1. Schema and template
- [ ] 1.1 `kaine/decision/__init__.py`, `kaine/decision/schema.py`: the 14 question templates, options, definitions, examples, near-miss categories, `SCHEMA_VERSION = 1`, and a function that builds the `/v1/systemone` `questions` object for a list of question ids.
- [ ] 1.2 `kaine/decision/systemone.jinja` and a renderer that produces a training prompt and its answer letter.
- [ ] 1.3 Tests: every question has at least three examples of each kind; option letters are single tokens for the Qwen3.5 tokenizer (skipped with a reason when the tokenizer is absent); rendering is deterministic; state comes before the question in the prompt.

## 2. Gold items and labelling page (early)
- [ ] 2.1 `scripts/k1jev/build_data.py gold`: about 420 items from a separate generation run, near-miss share of at least 40% per question, written outside the repository.
- [ ] 2.2 `scripts/k1jev/label_server.py` per design section 5.
- [ ] 2.3 Tests: bind address other than 127.0.0.1 refused; requests without the token or with a foreign Host header get 403; the page never contains the generated label; answers are fsynced and resumable; the default label path is git-ignored.
- [ ] 2.4 Tell the integrator the page is ready, with the item count, so the operator can be scheduled.

## 3. Training data
- [ ] 3.1 `build_data.py fetch`: Banking77 CSVs at a pinned commit (SHA-256 checked) and MultiNLI parquet at the pinned revision, fiction genre dropped.
- [ ] 3.2 `build_data.py generate`: synthetic train and dev through a temporary local llama-server under the GPU lock, with the rule filter and the second-pass label check.
- [ ] 3.3 Refusal of any path under the data root or `state/`, and no input for arbitrary text files; tests prove both.
- [ ] 3.4 Data manifest: per-source counts, label balance, hashes, licences.

## 4. Training
- [ ] 4.1 `scripts/k1jev/train_sft.py` per design section 6, with the running-cycle guard.
- [ ] 4.2 Tests with a tiny fake model under the kaine venv: argv has no shell, the loss mask covers only the answer letter, the guard refuses with a cycle present.
- [ ] 4.3 Train 4B and 0.8B (GPU window announced to the integrator first).

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
