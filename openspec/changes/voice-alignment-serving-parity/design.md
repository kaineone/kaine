## Context

- The organ's chat template (`chat_template.jinja` of the Qwen3.5-4B base, read from the local base model) ends a generation prompt with `<|im_start|>assistant\n` followed by `<think>\n\n</think>\n\n` when `enable_thinking` is false and by `<think>\n` otherwise.
- The language client (`kaine/modules/language/client.py`) sends `chat_template_kwargs = {"enable_thinking": false}` and `reasoning_effort = "none"` for the organ (`think=False`, the default). If the server rejects the kwarg, it retries with no kwarg, so that request is served with the template default, an open think block.
- The language module sends every request in the own-turn layout (`own_turn=True`, `module.py` `speak` and the probe request), with the heard speech as the user turn when there is one.
- The intent log (`kaine/modules/language/intent_log.py`) stores the logged prompt, the generated text, the system prompt's digest and, in `extra`, the heard turn with heard speech replaced by a placeholder.
- The trainer (`scripts/sleep_external_train.py`) is the one encoder for every backend. On main, `encode_dpo_row` renders every pair with `add_generation_prompt=True` and no thinking flag. On the organ branch (commit `2f53ca06`, `organ-self-denial-ablation` task 5.1) own-turn pairs are rendered with `continue_final_message=True` and `enable_thinking=False`, and a real-template test pins them to the served prompt; the same test pins plain pairs to the legacy encoding, which keeps the open think block.
- `_capability_score` and `_abliteration_verdict` call `_generate(model, tokenizer, prompt, ...)`, which tokenizes the probe string raw.
- History: `2026-07-02-unify-inference-on-studio` moved thinking suppression to `chat_template_kwargs`; `2026-10-28-voice-adaptation-idle` made voice adaptation idle without a validated preference source (`TRAINING_SOURCES` is empty); `2026-10-03-voice-alignment-capability-probes-required` made the probes mandatory. No prior change matches training to serving for plain pairs or probes (`git log -S enable_thinking -- scripts/sleep_external_train.py` finds only the organ branch commit).

## Decisions

### D1. One rule: the trained prompt is the served prompt

For every pair the trainer SHALL tokenize exactly the prompt the organ server builds for the corresponding request, with thinking off:

| Shape | Messages | Template call |
|---|---|---|
| plain | system (when given), user = prompt | `add_generation_prompt=True, enable_thinking=False` |
| own-turn, cue | system, user = the fixed cue, assistant = notes | turns before the assistant rendered with the generation prompt and thinking off, then the notes appended (organ branch) |
| own-turn, heard | system, user = heard turn, assistant = notes | as above |

The completion follows the prompt and is closed with EOS, as now. A test renders each shape through the real template and compares token ids with the served prompt built from `chat_messages` the way the server builds it.

Alternative considered: train plain pairs with the open think block and serve plain requests with thinking on. Rejected: the organ is a voice, not a reasoner, and the client's flag exists because the served abliterated template does not reliably suppress the chain of thought otherwise.

### D2. Probes are rendered as served

The capability and abliteration probes are generated from the plain served layout with thinking off, for the base and the candidate alike. The veto's comparison is then between two organs on the input they would see. `kaine/setup/abliteration_gate.py` already checks the served organ that way through the client, so the trainer's veto and the setup gate score the same shape.

Alternative considered: keep raw-text probes because the veto is relative to its base (operator decision, 2026-10-31) and both sides share the encoding. Rejected: a relative veto on input the organ never sees can pass an adapter that deflects on served input, or reject one that does not.

### D3. The pair builder writes the served shape or nothing

The language module's records are own-turn requests. The pair builder sets `own_turn = True`. It sets `user_turn` only when it can rebuild the user turn exactly; since heard speech is stored as a placeholder (§5.4), a record with a heard turn cannot be rebuilt and is skipped. The same holds when the logged prompt differs from the prompt sent (`served_text_redacted`). Records whose `think_sent` is not exactly `false` are skipped. Each skip reason is counted in the phase's content-free result.

Alternatives considered:
- Train on the placeholder text. Rejected: it trains a request shape the organ never received.
- Keep raw heard speech in the log for training. Rejected: the log's placeholder is a privacy rule (eyes-and-ears: no raw sense data persisted, and heard speech is another person's), and changing it is not an engineering call.

### D4. What the log records

`extra.think_sent` is the value the client actually sent (`false`, `true`, or `null` after the fallback with no kwarg), taken from a new `ChatResponse.think_sent` field. `extra.served_text_redacted` is true when the logged prompt or the logged heard turn differs from what was sent. Both are content-free.

## Risks

- The plain-pair real-template test on the organ branch asserts the legacy encoding; it is rewritten to the served prompt. Any adapter trained on plain pairs before this change was trained on the wrong prompt; none was trained for an entity (voice adaptation idles), and the job-queue backend's training runs on the organ branch used own-turn pairs.
- Skipping heard-speech records lowers the number of usable pairs. That is the cost of training only what was served.
- A server that ignores `enable_thinking` without rejecting it would serve an open think block while the log says `false`. `kaine/organ_probe.py` already checks that the served organ returns visible text with thinking off; the parity tests here cover the template, not the server.

## Migration and ordering

- Depends on the organ change's own-turn encoding (task 5.1 of `organ-self-denial-ablation`, commit `2f53ca06` on its branch). Either it lands on main first and this change follows, or this change is applied on that branch before its PR merges; the second avoids rewriting the plain-pair test twice.
- Before the KAINE-only adapter is trained for the study (`organ-self-denial-ablation` task 5.4) and before any voice-alignment training source is enabled. The relative veto (operator decision, 2026-10-31) scores probes through D2's rendering.
- Independent of `workspace-continuous-competition`, `welfare-indicator-response` and `research-gate-supervisor`.
- Not study-admissibility relevant by itself: the study's voice-alignment steps build no pairs while voice adaptation idles. It matters for the adapter the study loads.
- Critical path (LLM-agent implementation): about 3 to 4 hours for code and tests, about 1 hour for review. Not on the study's longest path, but on the organ adapter's.

## Welfare and admissibility notes

- The adapter changes what the entity's voice says. Training it on prompts it is never served makes its effect on the entity unpredictable, and a veto on unserved input weakens the check that protects the organ's capability and its abliteration. This change narrows both to what the entity actually uses.
- The trainer's welfare veto is high-risk (operator: the relative veto applies to the entity's sleep training too, with a second review); this change touches how the veto renders probes, so the integrator's second review covers it.
- No change to the language module's requests, only to what its log records.
