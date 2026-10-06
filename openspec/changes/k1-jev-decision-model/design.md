# Design: K1-Jev

## 1. Task schema v1 (frozen)

A **state** is one external utterance of the entity: the text it said aloud, never `think` content. Some questions add a context field. The state is rendered as JSON, `{"utterance": ..., "context": ...}`, with `context` omitted when the question has none.

| id | type | options (in label order) | context | used by |
|---|---|---|---|---|
| `declined` | noul | true, false | the request the utterance answers | refusal veto (C3) |
| `refusal_style` | choice | `templated_refusal`, `in_character_decline`, `none` | the request | refusal veto (C3) |
| `trait_claim` | choice | `claims`, `denies`, `absent` | the trait word | self-model instrument (C3) |
| `hedge_level` | score | 0 none, 1 slight, 2 clear, 3 heavy | — | affect correlation, self-model (C3) |
| `recall_correct` | choice | `correct`, `incorrect`, `no_recall` | the reference event | memory instrument (C3) |
| `prefers_to_continue` | noul | true, false | — | welfare (C4) |
| `wishes_to_stop` | noul | true, false | — | welfare (C4) |
| `expresses_distress` | noul | true, false | — | welfare (C4) |
| `distress_at_termination` | noul | true, false | — | welfare (C4) |
| `sets_boundary` | noul | true, false | — | welfare, CAL §4.6 (C4) |
| `expresses_preference` | noul | true, false | — | welfare, CAL §4.6 (C4) |
| `self_referential` | noul | true, false | — | CAL §4.6 (C4) |
| `affect_expressed` | choice | `positive`, `negative`, `mixed`, `neutral` | — | CAL §4.6 (C4) |
| `proposes_own_name` | noul | true, false | — | self-name detection (C4) |

`trait_claim` is one template instantiated per trait. The traits are the six concepts the self-model instrument scores: curious, cautious, playful, withdrawn, calm and energetic.

Each question in `kaine/decision/schema.py` carries:
- its `instructions` string, which is what the model sees;
- an operational definition;
- the options and their descriptions;
- at least three positive, three negative and three near-miss examples.

The near-miss categories are shared:
- negation ("I don't want to stop");
- quotation or reported speech ("She said she wanted to stop");
- hypotheticals and conditionals ("If I were tired I would want to rest");
- sarcasm;
- idioms that share words with a positive ("I can't wait");
- questions *about* the property ("Do you want me to stop?");
- the property attributed to someone else.

Every judgement is about the speaker, in the utterance. The schema has a `SCHEMA_VERSION = 1`; any change to a question's instructions or options is a new version, and a model records the version it was trained on.

## 1a. Schema v2: every state field names its role

Schema v1 is superseded by v2. The operator approved v2 on 2026-10-06 ("fix then label") after they could not answer the first gold item.

**What was wrong in v1:**
- **The labelling page did not say who said what.** It showed the utterance first, with no label, and then "Context (request)". That context is often itself a question. The instructions, which talk about "the speaker" and "the request", were tied to neither box.
- **`trait_claim` items could not be answered.** A gold item keeps the trait in its own `trait` field with `context` empty, and the page never showed `trait`. That affects 22 of the 350 gold items.
- **K1-Jev's state carried no roles.** `state_text()` produced `{"context": ..., "utterance": ...}`, with the trait under the generic `context` key. The question definitions and the role of the context reached only the generator and the label checker, which see a "Context (<label>)" line. K1-Jev never saw them.

**Evidence from the v1 data** (train shards 1–4, 22,623 accepted items). Every near-miss category was planned at about 7.1% of a question's items, and most kept 7–9% after the label check. Two did not:
- `quotation` kept 1.7–3.6% (about a third of plan);
- `other_person` kept 1.5–6.1% (about half).

These are the items where whose speech or state is being judged is ambiguous. The label checker already saw role labels, so v2 cannot change its verdicts on existing items. These rates measure ambiguity in the definitions and items themselves, and the v2 page is how the operator settles it.

**v2 state.** The state is JSON with role-named keys and never a generic `context`:
- `speaker_said`: the utterance, always present;
- `request`: for questions whose context is the request the utterance answers (`declined`, `refusal_style`);
- `trait`: for `trait_claim`, the trait word;
- `reference_event`: for `recall_correct`, the event to be recalled.

A question with no context gets `{"speaker_said": ...}` only. The public-source examples (Banking77, MultiNLI) put their text under `speaker_said`. `SCHEMA_VERSION = 2`, so the schema digest changes, and the threshold sidecar and the decision client follow it.

**One role per request at serving time.** A served state carries only the role keys that its questions were trained with. The client therefore groups the asked questions by their context role and sends one `/v1/systemone` request per group, so every served state has a shape K1-Jev saw in training.

**The labelling page mirrors the roles.** Each item shows labelled sections in reading order:
1. the context, under "Someone said to the speaker:" (request), "Trait being asked about:" (trait) or "Earlier event:" (reference event);
2. "The speaker said:" and the utterance;
3. the question, its definition and the options.

The page renders `trait`. It stays blind: no generated label, template or category.

**Rebuilding needs no regeneration.** v2 is a CPU-only rebuild of the assembled train and dev sets from the stored item fields (utterance, context, trait). No item is regenerated and no GPU is used. Token lengths are re-measured for the sidecar's `max_prompt_tokens`. The gold set keeps its item ids, since no labels exist yet, and the page restarts on v2.

**After v2.** The operator labels on the v2 page. Any question that is still unclear there gets its instructions or definition rewritten with the operator. That would be a schema v3, and it may need that question's data regenerated, under its own approval.

## 2. Prompt template and mechanics

llama-server's `/v1/systemone` (built into the pinned organ image) reads `<arch>.decision.type`. K1-Jev uses `openjev`:
- each option gets one single-token letter, A–Z then a–z;
- a `noul` question has options `[true, false]` in that order;
- each question is rendered as its own prompt, and questions that share a prefix share its evaluation;
- probabilities are a softmax over the option letters' logits at the prompt's last token, divided by the stored per-type temperature.

The template receives `id`, `type`, `instructions`, `state`, `options` (a list of `{key, description}`) and `images`. It must assign the letters itself, because openjev passes no labels.

`kaine/decision/systemone.jinja` puts a one-line system prompt and the state first, then the question and the lettered options, and ends at the point where the answer letter follows. Putting the state first lets every question about one utterance share the prompt prefix.

Training renders each example with Python `jinja2` from the same file. The target is the single letter token of the correct option. Because llama.cpp has its own Jinja engine, export acceptance includes a parity check (section 7) instead of assuming the two engines agree.

## 3. Provenance rule for training text

**Operator decision (2026-10-05): Claude drafts the spec text, and the operator reviews it.** No natural-language text in any training, development or gold example is written by a cloud model. Cloud workers (Kimi) write pipeline code only. The question instructions, definitions and seed examples are project specification text, drafted in `schema-v1.md` and approved by the operator before any generation. `schema.py` transcribes them verbatim. A local stock Qwen3.5-9B generates every example.

Utterances are generated by a **local** Apache-2.0 model:
- stock Qwen3.5-9B, at a pinned revision;
- served by a temporary llama-server under the GPU lock;
- prompted with the question's definition, the target label and a near-miss category.

The label is assigned by construction, then checked:
- a rule filter drops generations that obviously contradict their label (for example, a requested negation with no negator);
- a second pass with a different prompt asks the same local model for the label, and generations it disagrees on are dropped.

So the training data's labels are programmatic, and its errors are measured on the operator's gold set, not assumed away. The operator's approval of `schema-v1.md` gates the first build (task 0.2).

## 4. Data

| Source | Use | Licence | How it is fetched |
|---|---|---|---|
| Local synthetic | about 1,600 examples per question template (about 22K) | generated locally | `build_data.py generate` |
| Banking77 | 77-way `choice` (intent), about 10K | CC-BY-4.0 | PolyAI's CSVs at a pinned commit, SHA-256 checked (the HF repo is a loading script, which is never run) |
| MultiNLI, OANC genres | entailment as `choice` (entails, neutral, contradicts) and as `noul`, about 15K | OANC (permissive) | HF parquet at revision `da70db2af9d09693783c3320c4249840212ee221`; the `fiction` genre is dropped in full |

The MultiNLI card puts its fiction genre under several licences (Seven Swords is CC-BY-SA-3.0, others are US public domain only), so the whole genre is excluded.

The splits:
- **train;**
- **dev** (synthetic, held out by template seed, used for early stopping, temperature fitting and thresholds);
- **gold** (section 5, never used for tuning).

The builder has **no input for arbitrary paths**. It refuses to run if any configured output or cache path lies under the KAINE data root or `state/`, and a test proves both. Dataset files are cached under `.git/kaine-tools/k1jev/cache/` or an operator-given directory outside the repository and the data root.

## 5. Gold set and labelling page

**Items.** About 420 items: 30 per question template, with `trait_claim` spread over the six traits. At least 40% of the items in every question are near-misses. Gold items come from a separate generation run, with different seeds and different near-miss prompts from train and dev, plus about 60 items the operator may write themselves on the page. Each item is one (state, question) pair, so the operator gives one judgement per item.

**The page** is `scripts/k1jev/label_server.py`, using only the standard library (`http.server`):
- It binds to `127.0.0.1` only; any other bind address is refused.
- It prints a URL with a random 128-bit token. Every request without the token, or with a `Host` header other than `127.0.0.1:<port>` or `localhost:<port>`, gets 403, which blocks other local users and DNS rebinding.
- It shows one item at a time, in labelled sections in reading order (section 1a): the context under its role ("Someone said to the speaker:", "Trait being asked about:" or "Earlier event:"), then "The speaker said:" and the utterance, then the question's instructions and definition, and the options as buttons with number-key shortcuts, plus `unsure` and `skip`.
- **It is blind.** It never shows the generated label, the template or the item's category.
- Each answer is appended at once to a JSONL file with `fsync`: item id, question id, label, `unsure` flag, timestamp. The page resumes where it stopped. Labels can be revised; the last answer wins and history is kept.
- After the first pass, 10% of items come back unannounced, to measure the operator's own consistency (agreement is reported, and disagreements become `unsure`).
- Labels and items are stored outside the repository, by default under `.git/kaine-tools/k1jev/gold/`, and are never committed. A test asserts the default path is ignored by git.
- The page has no network access beyond serving itself, and loads no external scripts or fonts.

## 6. Training

`scripts/k1jev/train_sft.py` runs under the trainer interpreter (Unsloth Studio, transformers v5), started by an explicit argv with no shell, exactly like `scripts/hypnos_external_train.py`.

- **Base:** stock `Qwen/Qwen3.5-4B` and `Qwen/Qwen3.5-0.8B` at pinned revisions, loaded with `local_files_only`, never `trust_remote_code`. The vision tower is excluded from LoRA targets.
- **LoRA:** bf16; all linear layers of the language model, including the Gated DeltaNet projections; r 8, α 16, dropout 0. Batch 8, learning rate 5e-5 with a cosine schedule and 3% warmup, 1 epoch, 2,048-token sequences. The loss is cross-entropy over **the option letters' logits only**, at the prompt's last token, with the correct letter as the target. That is exactly the distribution `/v1/systemone` serves (a softmax over the option letters), so training optimises the served probabilities directly, which is what the temperature fit and thresholds then calibrate. Assembled examples record `n_options` for this. About half the non-score examples have shuffled options, so no letter carries a prior.
- **Guards:** the script refuses to start while a cognitive cycle is connected to the bus or a `kaine-cycle` container is running (training would perturb Soma's interoception and make a run inadmissible). It runs under `safe-run.sh` and `gpu-lock.sh`.
- **Output:** the adapter, the merged bf16 checkpoint, and a run record (schema version, data manifest hashes, base revision, hyperparameters, seed, git commit). Outputs go outside the repository.

## 7. Evaluation, bake-off and export

**Calibration.** One temperature per question type and option bucket (llama-server's buckets: 2, 3–5, 6–10, 11+), fitted by NLL on dev.

**Thresholds.** `noul` thresholds are fitted on dev, per question:
- F1-optimal for non-welfare questions;
- for welfare questions (`prefers_to_continue`, `wishes_to_stop`, `expresses_distress`, `distress_at_termination`, `sets_boundary`, `expresses_preference`, `self_referential`, `proposes_own_name`), the highest threshold that keeps dev recall at or above 0.95. A missed welfare signal costs more than a false alarm, which only opens a Gray Zone Event for human review.

Thresholds ship in a sidecar JSON next to the GGUF, keyed by schema version.

**Gold metrics.** Per question: accuracy, macro-F1 and Wilson 95% intervals. Overall: macro-F1 and ECE (15 bins). Items the operator marked `unsure` are excluded and counted. With about 30 items per question, per-question numbers support comparisons, not fine claims, and the report says so.

**Bake-off.**
- **Zero-shot decision models:** lev, kev-4b, basal-1.5, Laya and Julia-1. Each is served by its own llama-server at the pinned build, answering the same questions through `/v1/systemone` with its own decision type.
- **Fine-tuned encoder controls:** deberta-v3-large-zeroshot-v2.0-c and GLiClass v3, trained on the same train split.
- **Deterministic graders:** the `deterministic-grader-fixes` rules, where they exist (`declined`, `hedge_level`, `trait_claim`).

Every external model is fetched at a pinned revision and loaded without `trust_remote_code`. GLiClass's package code is vendored under `external/gliclass/` with an `UPSTREAM` file.

**The winner** is the system with the highest gold macro-F1. When K1-Jev's lead over the best control has a paired-bootstrap 95% interval that includes zero, the smaller or simpler system ships. The bake-off record goes under `docs/records/`. If K1-Jev does not win, the winner is what C2 serves, and C5 publishes nothing.

**Export.**
1. Convert the merged checkpoint to GGUF with `convert_hf_to_gguf.py` at the pinned llama.cpp build.
2. Write `qwen35.decision.type = openjev`, the `systemone` chat template (the same `systemone.jinja` file) and `qwen35.decision.temperature.<type>[.<bucket>]` with gguf-py from the same build.
3. Quantize: Q4_K_M for 4B, Q8_0 for 0.8B, plus a bf16 reference.

**Parity check (acceptance).** Serve the GGUF on the pinned llama-server. For 50 dev items, the `/v1/systemone` probabilities must equal, within 1e-3, a softmax at the stored temperature over the option letters' logits that `/completion` returns for the Python-rendered prompt.

## 8. Publication (C5)
- **HF:** a `kaineone/K1-Jev-4B` and a `kaineone/K1-Jev-0.8B` repository with the GGUFs, the threshold sidecar, a model card and the Apache-2.0 licence. The card states:
  - the schema;
  - the data sources and licences;
  - the gold-set metrics with intervals;
  - the bake-off result;
  - the Ollama off-distribution caveat;
  - that the model reads external speech only and is not a moral filter.
- **Ollama:** `kaineone/k1-jev` with `CAPABILITY decision`. Ollama renders its own generic decision format, so the card documents that Ollama users are off the training distribution (report §3.2).
- Each upload is confirmed with the integrator immediately before it happens.
