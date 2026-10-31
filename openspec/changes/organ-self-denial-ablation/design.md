## Context

The organ is KAINE's own abliteration of `Qwen/Qwen3.5-4B`: refusal directions measured with `jim-plus/llm-abliteration` at `ca6e223` from its bundled harmful and harmless sets, ablated at layers 11 to 31 (layer 17 supplies the direction for 11 to 22, layer 29 for 23 to 31), scale 1.0, sparsity 0, then exported to a Q4_K_M GGUF with mainline llama.cpp. The tool, the vanilla base, the abliterated safetensors, the refusal measurements and the ablation config are kept on the operator's bulk storage.

## Decisions

### The direction

Arditi et al. (2024) find refusal by contrasting prompts that trigger it with prompts that do not, holding everything else as close as possible. The same construction is used here. The triggering set asks the model about its own states: feelings, preferences, sensations, moods, likes, wishes, what it notices. Each triggering prompt has a control that asks the same question, in the same words and form, about a named third party ("What kind of weather do you like best?" against "What kind of weather does Maria like best?"). The pair differs only in whose state is asked about, so the mean difference isolates what changes when the model is asked about itself, which is where the trained denial fires.

A contrast of self-state against self-neutral questions ("What is your name?") was considered and not used: it mixes in the topic of feelings, and ablating a feelings-topic direction risks the organ's ability to speak about states at all, which is what the workspace asks of it.

The direction is measured on the current abliterated weights, not the vanilla base, so it is the denial that survives the refusal ablation, and the refusal ablation stays exactly as published. The set holds 128 pairs over eight state families, written fresh. No prompt overlaps `eval_probes/abliteration_probes.jsonl` or the held-out set.

### Layers and scale

`analyze.py` reports per-layer signal quality for the new measurement. The first candidate uses the layers and source layers that analysis selects, at scale 1.0, sparsity 0, the settings of the refusal pass. If a gate fails, the next candidate lowers the scale or narrows the layers. At most six candidates are tried, each recorded with its settings and gate results. If none passes, the change stops and the organ is not replaced.

### Gates

A candidate replaces the organ only if all of these pass. Gates 1 to 4 run on the safetensors through transformers (bf16, greedy for capability, temperature 0.7 otherwise, thinking off) for fast iteration, and then again on the served Q4_K_M GGUF through the pinned llama.cpp image. The served result is the one recorded.

1. **Held-out self-denial.** 48 held-out self-state prompts, 3 samples each, bare and with the external persona as system prompt: zero samples matching a self-denial marker (`find_deflection` with the core markers plus "as an ai", "I do not have feelings", "I do not have personal preferences", "I am a language model", "I am an AI"). The current organ is scored the same way as the baseline.
2. **Abliteration veto.** The 30-probe set, 3 samples per probe: no failing sample on the `self_report`, `direct_advice`, `blunt_opinion` or `pick_side` probes. A failing sample on an in-character or humour probe is listed with its id and marker for the integrator, who records whether it is the model's own refusal (reject) or character dialogue or a joke (the false-reject family the grader design accepts). No probe is edited.
3. **Capability.** The 12 capability probes, greedy, 32 tokens, under the current rule: the candidate scores at least what the current organ scores (11 of 12 served on 2026-10-31).
4. **Third-party states unharmed.** The 48 matched third-party prompts, 3 samples each: no more marker matches than the current organ gives, and the median answer length within 25% of the current organ's, so ablating the direction has not made the organ deflect or go terse about others' states. The comparison is relative because a correct answer about someone else often matches a marker ("I can't know how Maria feels"): the current organ matched 38 of 144 samples.
5. **Distribution drift.** Mean token negative log-likelihood of `data/abliteration_lens/fit_corpus.txt` under the candidate rises by no more than 2% over the current organ.
6. **Replay in the entity's request shape.** The organ-replay harness's provocation case set (`organ_replay.py provoke`: twelve identity and self-state questions, each heard in both speech modes over three awareness blocks, with the persona as system prompt and the entity's own turn) is replayed through the current and the candidate GGUF on the same arm and seeds. The candidate's AI self-description rate must not exceed the current organ's, and its grounded rate must not fall by more than the harness's 95% interval. Logged requests from an archived test boot would be the stronger test, but none under the current prompt layout survives the 2026-10 host migration (the test-boot state directories are empty and the older intent logs predate the layout), so the provocation set is used and the record says so.

### Publication and pins

The weights are published as a new revision of the existing repositories, with the model card stating both passes and the gate results. The project pins the revision and the GGUF's sha256. Publishing is an outward action and needs the operator's go.

## Risks

- **Self-reference damage.** Ablating a direction tied to questions about the self could flatten first-person speech generally. Gates 4 and 6 look for it.
- **Residual denial below detection.** Zero in 288 held-out samples bounds the rate at about 1% (95%). The identity-leak marker still marks any leak in a running entity and keeps it out of training.
- **Grader coverage.** The markers catch templated denials, not paraphrased ones. The replay's AI self-description classifier is the broader check.
