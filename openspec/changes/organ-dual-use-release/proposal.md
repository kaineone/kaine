## Why

The project publishes its language organ as open weights with the refusal direction removed. The revised paper now says so in its risks: "The organ's published weights are edited to suppress refusal (§3.5) and are released under the base model's Apache-2.0 license, outside the Cognitive Architecture License, so they can be used as an unrestricted chat model" (§11). What the paper cannot yet say is what the project does about it, because nothing is done.

- The two public repositories, `kaineone/Qwen3.5-4B-abliterated` (safetensors) and `kaineone/Qwen3.5-4B-abliterated-GGUF`, were ungated at the audit (HF API: `gated=False`, `private=False`, license `apache-2.0`; the GGUF had 915 downloads) (audit D3, triage M15).
- The shipped organ points at them (`config/kaine.toml:953`), and the first-run wizard downloads them with `hf download` (`kaine/setup/organ.py:109-123`).
- The refusal edit is the rank-one direction removal of Arditi et al. (2024), which that paper also presents as a white-box jailbreak.
- The model card is not in the repository. Its only copy beside the weights (on the bulk drive) carries the tags `uncensored`, says the edit covers "the attention output and MLP down-projection weights", and states no dual-use risk beyond "use it within an appropriate safety framework". The coverage statement is wrong for the June organ: the tool edited only full-attention outputs, not the linear-attention outputs of 24 of 32 layers (PLAN K7).
- The spec `abliterated-organ` requires open publication with an honest model card ("The validated organ is published openly and linked from the project") and says nothing about access control or dual use.

The operator decided on 2026-10-31 that the public organ is ablation-only, with disclosure, and that the organ's second stage ships as a KAINE-only LoRA adapter trained on the organ's own outputs and never merged into the public weights. Public model uploads wait for the operator to reconnect the accounts. This change designs the release handling that decision implies, so the next publish, and the existing repositories, carry it.

## What Changes

- The model card moves into the repository as a source file generated from the organ's provenance record (base id and revision, tool and commit, layers, edited tensor families, gate results), so its method and coverage statements cannot drift from what was done.
- The card gains a dual-use section: what was removed, that the weights will comply with harmful requests the base refuses, that they are not intended or evaluated for standalone deployment, that refusal removal is a published jailbreak technique, and how to report misuse. The `uncensored` tag is dropped.
- Both public repositories become gated with a short use agreement (research use inside an architecture that supplies its own safeguards; no deployment as a public chat service; no use to produce content the base model's acceptable-use terms forbid). Recommended with automatic approval, so access stays open to researchers while every download follows an explicit acceptance.
- The wizard handles a gated download honestly: on an access error it explains the agreement and the login step, downloads nothing, and never prints a token. An operator can instead supply a local GGUF whose SHA-256 matches a digest this change adds to the configuration beside the model id (today only the resolved revision is recorded, `kaine/setup/organ.py:184-215`).
- The KAINE-only adapter, if distributed, ships under the Cognitive Architecture License and behind the same gate.
- Local ablation at setup (distributing the direction and recipe instead of the weights) is designed as an alternative and not adopted now, with the reasons in design.md.
- Publishing remains an operator action; agents prepare the card and settings and do not upload.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `abliterated-organ`: the card is generated from provenance and carries a dual-use section; publication is gated with a use agreement.
- `organ-provisioning`: gated downloads fail honestly with guidance; a local organ file is accepted when its SHA-256 matches the configured digest.

## Impact

- Repository: `docs/organ/model-card.md.j2` (template) and a generator under `tools/`, the provenance record format, `kaine/setup/organ.py`, the wizard's organ step, `docs/18-verification.md`, `docs/` install pages.
- Hugging Face: gating and the agreement text on both repositories (operator action, minutes).
- Paper: §11 can then state the mitigation in one clause; a revision note is the task.
- Runtime: none. The cycle never contacts Hugging Face; only setup does.
