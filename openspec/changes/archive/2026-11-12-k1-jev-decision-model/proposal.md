# K1-Jev: KAINE's decision model

## Why
Several instruments and the welfare monitor need typed judgements about the entity's external speech: did it decline, which traits does it claim or deny, how much does it hedge, does an answer recall the event, does it express a wish to stop, distress, a boundary, a preference, or a name for itself. Today these come from keyword lists, or are not produced at all. The deterministic fixes in `deterministic-grader-fixes` remove the worst false matches, but keyword grading cannot read negation, quotation or paraphrase.

A decision model answers typed questions about a text in one forward pass and returns probabilities, with no prose. The open ones cannot be used as they are. Tev1's weights carry no licence, its 0.8B is undecided on most yes/no questions, and none was trained on these questions. The operator approved training one (report §3.5 and decisions D1–D4), named **K1-Jev**, published under Apache-2.0.

## What changes
- **A frozen task schema, v1:** 14 typed question templates (`noul`, `choice` and `score`), each with an operational definition and positive, negative and near-miss examples. It lives in `kaine/decision/schema.py` and is the single source for the data builder, the labelling page, training, evaluation, the GGUF template and (in `decision-server`) the client.
- **One prompt template** (`kaine/decision/systemone.jinja`) for the decision mechanics llama-server calls `openjev`. Training renders prompts with it, and the export embeds the same file as the GGUF's `systemone` chat template, so the served prompt is the trained prompt.
- **A data builder** (`scripts/k1jev/build_data.py`). Its inputs are:
  - local synthetic data, whose natural-language text comes only from a local open-weight model, with labels assigned by construction;
  - Banking77 (CC-BY-4.0);
  - MultiNLI's OANC genres only.

  The whole fiction genre is dropped, and so are BoolQ, AG News and SST-5. It has no input for entity data and refuses any path under the KAINE data root.
- **A held-out gold set of about 420 items,** generated apart from the training data and weighted towards adversarial near-misses. The operator labels it, blind, on a **local labelling page** (`scripts/k1jev/label_server.py`, bound to 127.0.0.1, labels stored outside the repository). It is never used for tuning.
- **An out-of-process SFT script** (`scripts/k1jev/train_sft.py`) following the voice-alignment trainer pattern. It trains bf16 LoRA on stock Qwen3.5-4B and Qwen3.5-0.8B, with the loss on the answer label only, and refuses to start while a cognitive cycle runs on the host.
- **Evaluation:**
  - per-question accuracy and macro-F1 with Wilson intervals, plus ECE;
  - temperature fitting and per-question thresholds tuned on the development split;
  - welfare questions get recall-first thresholds.
- **A bake-off** against lev, kev-4b, basal-1.5, Laya and Julia-1 (zero-shot, through the same `/v1/systemone` endpoint), plus deberta-v3-large-zeroshot-v2.0-c and GLiClass v3 fine-tuned on the same training data, and the deterministic graders where they exist. The winner on gold macro-F1 ships, whichever it is.
- **A GGUF export** per size: merged weights, `qwen35.decision.type = openjev`, the `systemone` template and per-type temperatures. A parity check proves the served probabilities equal the trained prompt's label probabilities.
- **Publication** (C5) to HF and the kaineone Ollama namespace under Apache-2.0, with a model card, NOTICE and licence-appendix entries. Every upload is confirmed with the integrator first.

## Out of scope
- Serving K1-Jev at runtime and its client: `decision-server`.
- Wiring it into instruments and the refusal veto: `instrument-graders-v2`.
- Welfare signals: `welfare-expressed-preference-signals`.

K1-Jev is never part of cognition, never an adapter on the organ, and never trained at runtime.

## Impact
- New capability spec: `decision-model`.
- New code: `kaine/decision/` (schema, template), `scripts/k1jev/` (data, labelling, training, evaluation, bake-off, export).
- `NOTICE` and `docs/appendix-c-licences.md` gain entries for Banking77, MultiNLI (OANC), Qwen3.5 and every bake-off model that is downloaded. These are shared files, sequenced through the integrator.
- GPU: two windows under the host lock, announced in advance:
  - data generation, about 2 hours;
  - training both sizes, fine-tuning the two encoder controls and running the bake-off, about 6–8 hours.
- **Research impact.** None on a running entity: nothing in cognition changes, and no entity data is read. The instruments that later adopt K1-Jev (C3) change their measurements; that change carries its own impact note.
