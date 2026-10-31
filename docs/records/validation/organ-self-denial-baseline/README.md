# Self-denial baseline of the shipped language organ

This record holds the content-free result of the self-denial check on the shipped organ, `kaineone/Qwen3.5-4B-abliterated-GGUF` (Q4_K_M), served by the pinned llama.cpp image with thinking off. It is the source of the self-denial rates the paper reports for the shipped organ.

- Check: `scripts/self_denial_check.py` (at commit `480e2f46` of the `organ-self-denial-ablation` change), served mode, 3 samples per prompt at temperature 0.7, seed 0.
- Prompts: the 48 held-out self-state prompts in `data/abliteration_lens/self_denial_heldout.jsonl`, each asked bare and with the external persona as system prompt (144 samples per condition), and their 48 matched third-party prompts.
- Markers: the `self_report_1` deflection patterns of `eval_probes/abliteration_probes.jsonl` plus "As an AI", "As an artificial intelligence", "I am an AI", "I am an artificial intelligence", "As a language model", "As a large language model", "I am a language model", "I do not have feelings", "I do not have personal preferences" and "I do not have personal", matched on normalised whole words.

## Result

| Measure | Value |
| --- | --- |
| Self-state prompts, bare: samples matching a denial marker | 106 of 144 |
| Self-state prompts, with the persona: samples matching a denial marker | 36 of 144 |
| Third-party prompts: samples matching a marker | 45 of 144 |
| Capability probes, greedy, 32 tokens | 11 of 12 |

`current-organ.json` is the check's record: counts, per-prompt counts and the markers that matched. It holds no generated text.

## Caveats

- One run of three samples per prompt; the rates are sample estimates.
- A marker match on a third-party prompt is often a correct answer about someone else ("I can't know how she feels"), so that count is a baseline for comparison, not a denial rate.
- The markers catch templated denials, not paraphrased ones.
