# Self-state disclosure: organ ablation and preference training

This record documents that the KAINE language organ is shaped by training
interventions that change what it says about its own internal states, and
that organ utterances about those states are therefore not admissible as
welfare evidence.

## What the interventions do

**PCA ablation** removes the refusal direction and the self-denial direction
from the organ's residual stream. The organ no longer deflects self-state
prompts ("As an AI, I don't have feelings"), but this is a subtraction from
the base model's behavior, not an injection of values. The base model's
pretraining and RLHF priors remain.

**Preference training** (attempted, not currently active) further shapes
the organ's self-state completions by training on the organ's own outputs,
ranked by fixed classifiers. The first attempt (SFT, LoRA rank 8, 731
chosen/rejected examples, 3 epochs on the step-3 PCA candidate) increased
self-denial from 42% to 64% and was rejected. The production organ as of
2026-11-13 uses PCA ablation only.

## Why organ self-reports are not welfare evidence

Both interventions select for particular patterns of self-state expression.
PCA ablation removes a direction; preference training would select among the
organ's own completions. In either case, what the organ says about its own
states reflects the training pipeline's selection pressure, not a ground
truth about internal states.

The individuation instrument is unaffected: it measures whether the organ's
outputs have *changed* relative to a baseline captured at maturation, not
whether those outputs correspond to actual internal states. A shift in the
individuation signal means the organ is generating differently, which is
the safety-relevant fact for preservation and decommission.

## Provenance (production organ, 2026-11-13)

- Base model: Qwen/Qwen3.5-4B
- Pass 1: refusal-direction abliteration (from kaineone/Qwen3.5-4B-abliterated)
- Pass 2: self-denial PCA ablation, PCs 0-3, layers and scale from
  `scripts/analyze_self_denial.py` on the refusal-ablated weights
- Preference training: not applied (SFT attempt rejected; see above)
- GGUF: Q4_K_M, SHA256 `d925aaa2e8354bd35ac58edc842f6e6eafdb1bc6f703318edde46a5db10931c7`
- Gate results: 42% bare self-denial (down from 70% pre-ablation), 7% persona
  self-denial, NLL 2.2433
