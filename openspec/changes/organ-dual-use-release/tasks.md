## 1. Card (repository only)

- [ ] 1.1 Provenance record gains an `edited_tensor_families` field per layer band; fill it for the June organ from the tool's code and a weight diff (the coverage finding K7), and for each new candidate from its run.
- [ ] 1.2 `docs/organ/model-card.md.j2` and `tools/render_model_card.py`; sections per design D2; the `uncensored` tag removed. Tests: `tests/test_model_card_render.py` (coverage follows the record; dual-use section present; no `uncensored` tag).
- [ ] 1.3 Verify, before the card says it, whether third-party refusal-ablated builds of the same base are public; otherwise the card omits the point.
- [ ] 1.4 Draft agreement text (design D1) for the operator; Claude second review of card and agreement.

## 2. Setup

- [ ] 2.1 `run_organ_download` recognises a gated-repository access error and reports it with guidance, no revision, no token output. Tests: extend `tests/test_organ_install.py` with a fake `hf` that exits as a gated repository does.
- [ ] 2.2 `[language].model_sha256` in config validation; the wizard's local-file path with the digest check. Tests: matching and mismatched files.
- [ ] 2.3 `docs/18-verification.md` and the install pages: the gate, the agreement, the offline digest path.

## 3. Operator actions (no agent uploads)

- [ ] 3.1 Operator: enable gating with automatic approval and the agreement on `kaineone/Qwen3.5-4B-abliterated` and `kaineone/Qwen3.5-4B-abliterated-GGUF`; replace both cards with the rendered card.
- [ ] 3.2 Operator: publish the next ablation-only candidate gated, with its rendered card and the digest filled into `config/kaine.toml`.
- [ ] 3.3 Operator decision: whether to publish the KAINE-only adapter; if yes, a separate CAL-licensed, gated repository.

## 4. Paper and close

- [ ] 4.1 Paper revision note for §11: the mitigation (gated access, use agreement, card).
- [ ] 4.2 `openspec validate organ-dual-use-release --strict`.
