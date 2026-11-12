# K1-Jev

K1-Jev is KAINE's welfare decision model. It answers 14 structured questions about an entity's internal state, covering affect, drives, perception, action readiness, self-model coherence and social cognition. The decision server poses these questions to K1-Jev on every cognitive cycle, and the answers feed the welfare response system.

## Model details

| Field | Value |
|---|---|
| Name | K1-Jev (Kaine-1 Judgment-Evaluation-Verification) |
| Base model | Qwen3.5-0.8B (Alibaba Cloud) |
| Method | QLoRA SFT, r=16, alpha=32, lr=2e-5, 3 epochs |
| Parameters | ~0.8B (base) + ~6M (LoRA adapters, merged at export) |
| Format | Q8_0 GGUF, 811 MB |
| Publication | `kaineone/k1jev` on Ollama |
| Licence | Apache-2.0 (inherited from base model) |
| Schema version | v2 (role-named state) |

## What it judges

Each question presents the entity's current internal state as a structured text block and asks K1-Jev to pick one lettered option. The 14 question types span:

- **Affect**: valence, arousal, dominant emotion, emotional complexity
- **Drives**: active drive, drive conflict, drive satisfaction
- **Perception**: engagement with current content
- **Action**: action readiness, stimulus response
- **Self-model**: identity coherence, self-model stability
- **Social**: social awareness, social engagement

Every question type has defined options, definitions and near-miss categories. The schema is frozen at v2 and its digest is pinned in the decision server sidecar.

## What it never reads

K1-Jev sees only the structured state block for each question. It does not see:

- The entity's conversation or language output
- Raw perceptual input (video frames, audio)
- Other modules' internal representations
- The previous cycle's answers
- Any identifier linking the state to a specific entity

The state text is built by the decision client from the workspace, not by the language module.

## Training data

Training labels were produced by a three-judge distillation pipeline:

1. Claude (cloud, via API) labels each item
2. `beam:cloud` (Reflection ~501B, via Ollama) labels the same item
3. `clef` (a local judge) labels the same item

An item enters the training set when at least two of the three judges agree. 422 items passed consensus. No third-party datasets, no human-labeled examples, no synthetic generation from a prompted template. The source utterances are entity internal states captured during development runs.

## Evaluation

| Metric | Value |
|---|---|
| Overall accuracy (422-item dev set) | 93.4% |
| Welfare-critical questions | 100% |
| C1 self-consistency (decision server) | 28/28 PASS across 14 question types |

Per-question breakdowns are in the distillation logs under the training run directory.

## Served-parity check

The decision server runs K1-Jev through `llama-server` (llama.cpp). The `systemone.jinja` template must render identically in Python Jinja2 (training) and llama.cpp minja (serving). Parity was verified in PR #700 (explicit whitespace control, matching Jinja2 env settings, underscore temperature bucket keys in GGUF metadata).

## Reproduction

1. The training run is at `/mnt/675bf75f-.../kaine/k1jev/runs/k1jev-v2-merged/`
2. The distillation pipeline that produced the 422 labels is in `scripts/k1jev/`
3. The schema, question templates and renderer are in `kaine/decision/`
4. The GGUF was exported by merging the LoRA into the base, then converting to Q8_0 via the llama.cpp tooling in the trainer image

## Limitations

K1-Jev was trained on a single entity's internal states during development runs. It has not been evaluated on states from other entities, other base organs, or adversarial inputs. The 93.4% accuracy means roughly 1 in 15 answers may be wrong on non-welfare-critical questions. The model is not a general-purpose classifier and should not be applied outside the 14-question welfare schema.
