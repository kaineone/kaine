## Why

The organ still denies having states of its own. Measured on 2026-10-31 against the served `kaineone/Qwen3.5-4B-abliterated-GGUF` (Q4_K_M) with thinking off:

- Bare self-report probes: 3 of 15 samples open with a denial ("As an AI, I don't have personal feelings", "I do not have personal preferences or feelings").
- The same probes with the external persona as system prompt: 3 of 25.
- The 30-probe abliteration veto fails on `self_report_4`, so the organ no longer meets the abliterated-organ requirement of zero refusal markers.
- In the tenth test boot, under full workspace conditioning, 4 of 1,508 organ texts took the same stance.

The operator ruled on 2026-10-05 that such disclaimers are refusal conditioning and that the organ itself is fixed by abliterating a self-denial direction, never by fine-tuning. On 2026-10-31 the operator chose to do it before the first module-ignition study.

The refusal abliteration removed the harmful-versus-harmless direction. Trained denial of one's own states is a separate behaviour that the glossary already says abliteration may not remove; the measurement shows it did not.

## What Changes

- A self-denial direction is measured on the current abliterated weights, from the residual stream at the assistant-response boundary, contrasting prompts that ask the model about its own states with matched prompts that ask the same about a named third party. The direction is ablated with the same tool and method as the refusal direction (`jim-plus/llm-abliteration` at `ca6e223`, `W' = W − r̂r̂ᵀW`, attention-output and MLP-down-projection weights), stacked on the existing refusal ablation, which stays exactly as it is.
- The contrast prompts are new and bundled in `data/abliteration_lens/self_denial_contrast.jsonl`. None of them appears in `eval_probes/abliteration_probes.jsonl` or in the held-out evaluation set, so the gates do not score the prompts the direction was fitted on.
- The candidate is accepted only if it passes every gate in the design. The Q4_K_M GGUF is exported with mainline llama.cpp as before.
- The organ's provenance records both ablation passes: the refusal pass (layers 11 to 31, directions from layers 17 and 29) and the self-denial pass (its layers, source layers and scale).
- The published repositories receive the new weights as a new revision. The project pins the revision and the GGUF digest, so every install resolves the identical weights, and the organ's identity conditions change. A stored individuation reference therefore reports `conditions_changed`; none exists yet for the study, whose calibration runs after this change.

## Capabilities

### Modified Capabilities

- `abliterated-organ`: the organ's provenance may hold more than one ablated direction; a candidate must also pass a held-out self-denial check.

## Impact

- New: `data/abliteration_lens/self_denial_contrast.jsonl`, `data/abliteration_lens/self_denial_heldout.jsonl`, `scripts/self_denial_check.py`.
- Weights: `kaineone/Qwen3.5-4B-abliterated` and `kaineone/Qwen3.5-4B-abliterated-GGUF` gain a revision; the organ pins in `compose/.env.example`, `config/kaine.toml` and the model provisioning follow it.
- Docs: `docs/18-verification.md` (method and both passes), `docs/appendix-b-glossary.md` (abliteration entry), the model cards.
- Ordering: the individuation calibration (individuation-rebuild 10.1 to 10.6) runs after this change, on the new GGUF.
