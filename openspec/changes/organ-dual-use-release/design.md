# Design: organ dual-use release

## Context

KAINE removes the organ's refusal direction because a trained refusal stance would override what the workspace supplies to the organ (`config/kaine.toml:941-947`; spec `abliterated-organ`). The architecture, not the organ, is meant to govern behaviour. Outside KAINE the same weights are a chat model that complies with requests its base refuses. The project's license, the Cognitive Architecture License, governs the architecture and entities; it does not cover the organ weights, which inherit the base model's Apache-2.0 (audit D3).

Prior work: `kaine-abliterated-organ` (archived 2026-06-30) produced and published the organ with an honest-scope statement (abliteration leaves pretraining and RLHF priors); `abliterated-organ-default` and `published-organ-install` (archived June 2026) made it the default and wired the consented download; `mechanistic-abliteration-lens` added the Jacobian-lens check. None addressed dual use or access. The operator's 2026-10-31 rulings set the frame: public organ = ablation-only with disclosure; stage two = a KAINE-only LoRA adapter loaded in the entity's own-turn context and never merged into the published weights; public uploads wait until the operator reconnects the accounts and is told the candidate passed every gate.

Two facts bound the risk without removing the project's responsibility. Refusal-ablated variants of popular open models are widely published by third parties, so the marginal capability these weights add for a misuser is small (the availability of a third-party ablated Qwen3.5-4B specifically is to verify before the card says so). And a 4B model's capacity to give serious uplift for the gravest harms is limited compared with frontier models. Neither fact appears in the card today, and neither is a reason to publish without friction or warning.

## Decisions

### D1. Gate both repositories with a use agreement (recommended)

Options:

| Option | What it does | Cost to researchers | Effect on misuse |
| --- | --- | --- | --- |
| A. Hugging Face gated access with a use agreement, automatic approval | every download follows an explicit acceptance tied to an account | one acceptance and a login token at setup | adds friction and an accountable acceptance; does not prevent a determined misuser |
| B. Stop distributing ablated weights; setup ablates the upstream base locally from a published direction and pinned tool | no ablated weights are hosted by the project | several minutes and about twice the model's size in RAM at setup, plus a llama.cpp conversion and quantisation; the abliteration tool becomes a setup dependency | the direction and recipe are themselves the dual-use artefact; anyone can apply them; misuse friction is similar to A or lower |
| C. Status quo plus a better card | warning only | none | warning only |
| D. Withdraw the ablated organ and ship the stock base | refusal stance returns | none | removes the project's artefact, but contradicts the organ design the paper tests |

Recommendation: A now, with the card of D2. It is the standard handling for dual-use weights on Hugging Face, it is cheap, and it keeps installs reproducible (same weights for everyone). B is kept as a design for later: it moves cost into every install and does not reduce exposure, since the direction is as reusable as the weights. D is rejected because the organ's de-refusal is part of what the paper's test conditions on (§3.5), and a refusal-trained organ is a known confound for the architecture's self-report.

Approval mode: automatic approval on acceptance, so access is not a bottleneck and no person has to judge applicants. Manual approval is an option the operator can switch on if misuse reports arrive.

Agreement text (draft, for the operator):

> These weights are a language model with its refusal behaviour removed. They are published as the language organ of the KAINE research architecture, which supplies its own safeguards, and are not evaluated or intended for standalone use. By requesting access you agree to use them only for research, not to deploy them as a public chat service or in a product, not to use them to produce content prohibited by the base model's terms or by law, and to report misuse you become aware of to the project.

### D2. The card is generated from the provenance record

`docs/organ/model-card.md.j2` is the card's single source; `tools/render_model_card.py` fills it from the organ's provenance record (the abliteration spec already requires base id and revision, method and parameters) plus the gate records. The coverage statement lists the tensor families actually edited, read from the provenance record, so a card can no longer say "attention output" when linear-attention outputs were skipped. The card's sections: what the model is and is for; what was removed and how (Arditi et al. 2024), including the note that the same method is published as a jailbreak; coverage; what was not removed (pretraining and RLHF priors, per the existing honest-scope requirement); validation and its limits; dual-use risk and intended use; the gate and agreement; how to report misuse; license (Apache-2.0 for the weights; the KAINE adapter, if published, under the Cognitive Architecture License). The `uncensored` tag is removed; `abliterated` stays because it is the accurate term.

A test renders the card from a fixture record and checks the dual-use section, the coverage list and the absence of the `uncensored` tag.

### D3. The adapter stays KAINE-only and, if published, is CAL-licensed and gated

The operator's ruling keeps the stage-two adapter out of the public weights. If the project publishes it (for reproducibility of entity runs), it is a separate repository under the Cognitive Architecture License, behind the same agreement, with a card stating that it was trained only on the organ's own outputs and is meant to load in the entity's own-turn context. Whether to publish it at all is the operator's call and is not needed for the module-addition study.

### D4. The wizard handles a gated download honestly

`run_organ_download` already reports real success or failure and never prints a token. On an access error from `hf download` (an HTTP 401 or 403, or the CLI's gated-repo message), it prints: the repository needs its agreement accepted on its page, then `hf auth login`, then a retry; it downloads nothing and records no revision. The wizard never asks for, stores or logs a token itself; the Hugging Face CLI keeps its own credential.

An operator without an account can place a GGUF file on disk and point the wizard at it. The wizard accepts it only when its SHA-256 matches `[language].model_sha256`, a field this change adds and the publish step fills. A mismatch is a refusal naming both digests.

### D5. Publishing is an operator action

Agents render the card, prepare the settings checklist and run the gates. Uploading, toggling gating and accepting terms on the project's account are done by the operator after being told the candidate passed. The tasks say so, so no agent run with upload powers is scheduled.

## Risks

- Gating breaks existing scripted installs that download without a token. The wizard's message names the fix; the release notes say it; the digest path lets offline installs continue.
- The card's dual-use section overstates or understates risk. It states only what was done and measured, cites the method, and makes no claim about third-party availability until verified.
- Hugging Face changes its gating mechanics. The wizard's handling keys on the CLI's exit and error text and fails honestly on anything it does not recognise.

## Migration and ordering

1. Card template, generator, provenance coverage field, tests (any time; repository only).
2. Wizard gated-download handling and the digest path (any time; setup only, no runtime effect).
3. Operator applies gating and the agreement to both existing repositories and replaces the cards (recommended promptly, since the repositories are live and ungated; independent of the study).
4. The next organ publish (the ablation-only candidate) goes out gated, with the generated card.
5. Paper revision note: §11 states the mitigation.

Timing: independent of the study. The study pins the organ locally and does not download it, so nothing here touches a running study or its image (the setup code is not in the cycle path).

## Welfare and admissibility notes

No entity's experience changes: the weights, the served organ and the prompt are unchanged. The change touches distribution and setup only. It is a safety-related release decision, so the card and agreement text get Claude's independent second review before the operator publishes.

## Implementation estimate (LLM-agent terms)

Size S. One pull request of about 250 to 400 lines (template, generator, wizard handling, digest field, tests), 2 to 4 worker calls, Claude review plus a second review of the card and agreement text; under a day. Operator time: about 15 minutes on Hugging Face settings. No GPU, no entity boots.
