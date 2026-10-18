## Why

The paper (§3.5 and Table A1, predictive-workspace-paper branch `notes-decoding`, for PR #47) now bounds the organ's decoding. Language-model text falls into self-reinforcing loops: once a sentence repeats, its probability of repeating again rises with each repetition (Holtzman et al. 2020; Xu et al. 2022). The sixth test boot of main 7b5ed07c had 3 of 137 internal texts looping on one sentence, the longest 2033 characters, until the 512-token cap cut it mid-sentence. The organ sent no repetition control, and an offline replay on the pinned llama-server build b11382 with the same GGUF shows the risk is far larger under greedy decoding, which the study configurations use (`temperature = 0.0`): 182 of 432 internal texts repeated a sentence and 126 ran to the cap.

## What Changes

- The organ's requests carry a DRY penalty (llama.cpp `dry_multiplier`, `dry_base`, `dry_allowed_length`, `dry_penalty_last_n`): extending a token run that already occurs in the context (persona, notes and the text so far) is penalized by `multiplier * base^(n - allowed_length)` for a match of `n` tokens. It is a graded form of n-gram blocking that leaves single-word reuse ("I") alone. Shipped values 0.8, 1.75, 2 and 2048 tokens; a multiplier of 0 (the default when the key is absent) sends nothing, so the body is unchanged.
- Think intents get their own token cap, `think_max_tokens` (128 shipped; absent means `max_tokens`), because inner speech is condensed (Alderson-Day and Fernyhough 2015); speak intents keep `max_tokens` (512).
- `sentence_cut` (true shipped; false when absent): a text is cut before its first verbatim repeated sentence of at least three words, and a text stopped by the token cap is cut back to its last complete sentence. The intent log's `extra.text_cut` records the reason and the generated length; a log line records the cut without content. The cut text is what is published, logged and returned.
- The individuation probe keeps its fixed conditions: `probe_request()` sends no DRY fields, its own `max_tokens`, and no cut, so `probe_conditions()` and `prompt_layout_digest` are unchanged.
- The in-process `llama_cpp` backend has no DRY sampler; it ignores the penalty and keeps the cut and the caps.

## Capabilities

### Modified Capabilities

- `language`: the organ's decoding carries a repetition penalty and per-mode token caps, and degenerate text is cut at a sentence boundary.

## Impact

- `kaine/modules/language/client.py`, new `kaine/modules/language/repetition.py`, `kaine/modules/language/module.py`, `kaine/boot/factories/language.py`, `config/kaine.toml`, `docs/09-modules/language.md`, `docs/appendix-a-configuration/modules.md`, new tests.
- Behaviour with the shipped config: fewer loops and capped thought; with the new keys absent every request body and published text is as before.
