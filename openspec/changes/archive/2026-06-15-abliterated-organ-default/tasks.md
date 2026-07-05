## 1. Shipped config (`config/kaine.toml`)
- [x] 1.1 `[lingua].model_id` → `huihui_ai/qwen3.5-abliterated:9b` (with sovereignty + scale-up comments)
- [x] 1.2 `[hypnos.voice_alignment].model_id` display label → same tag
- [x] 1.3 Remove `[evaluation].chat_model_id`; comment that it derives from lingua and fails closed on mismatch

## 2. Derive + fail-closed (`kaine/evaluation/config.py`)
- [x] 2.1 `EvaluationConfig` default `chat_model_id` → abliterated tag (fallback only)
- [x] 2.2 `from_mapping(cls, data, *, lingua_model_id=None)`: derive `chat_model_id` from lingua; raise `ValueError` on explicit divergent value
- [x] 2.3 `load_evaluation_config(path=None, *, lingua_model_id=None)`: thread `lingua_model_id` through both branches

## 3. Cycle coupling point (`kaine/cycle/__main__.py`)
- [x] 3.1 Load eval config + derive/guard at the TOP of `_boot_and_run` (before bus/modules/runtime.json)
- [x] 3.2 On `ValueError`: stderr operator message + clean `return 3`
- [x] 3.3 Reuse the computed `eval_cfg` at the sidecar block (drop the duplicate load)

## 4. Align internal defaults
- [x] 4.1 `kaine/modules/lingua/module.py` constructor default
- [x] 4.2 `kaine/modules/hypnos/voice_alignment.py` `VoiceAlignmentConfig.model_id`
- [x] 4.3 `kaine/boot.py` `make_hypnos` `VoiceAlignmentConfig` fallback

## 5. Tests
- [x] 5.1 `tests/test_evaluation_config.py`: derive / explicit-match / fail-closed mismatch / shipped-derives / shipped-organ-is-abliterated guard
- [x] 5.2 `tests/test_boot_wiring.py`: update model-id literals
- [x] 5.3 Targeted suite green; full suite green before PR
