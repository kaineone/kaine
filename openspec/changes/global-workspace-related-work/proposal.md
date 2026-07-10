# Situate KAINE against the emergent global workspace found in language models

## Why

Recent work reports that a global-workspace-like structure is empirically present
inside large language models: verbalizable representations that are broadcast and
read across the network, decoded with the Jacobian lens (Gurnee et al. 2026,
"Verbalizable Representations Form a Global Workspace in Language Models"). KAINE
is built as a **predictive global neuronal workspace**, so this is directly
relevant related work — evidence that the workspace frame is not merely a
borrowed metaphor but an empirically tractable structure in the substrate KAINE's
language organ is built from.

It must be cited **carefully**. The workspace that result describes is an
**emergent, intra-model** phenomenon inside a single transformer; KAINE's
workspace (Syneidesis) is an **explicit, architectural** one that selects and
broadcasts a coalition across sixteen modules. These are different constructs at
different levels of organization. Cited as motivation and related work, the result
strengthens the paper; misread as validation of KAINE's architecture, it would be
exactly the kind of overclaim the paper is otherwise careful to avoid. The
citation therefore ships **with** the emergent-vs-architectural distinction stated
plainly, not as a bare "see also."

This is a **documentation / paper** change (the deliverable lives in the
predictive-workspace paper repository, not the runtime). It carries no code. Per
the project's review-before-publishing rule, the lead reviews the wording before
it is committed to the paper.

## What Changes

- **Add a related-work citation** to the paper for the emergent-global-workspace
  result (Gurnee et al. 2026), positioned as motivation that global-workspace
  structure is empirically real in LLMs.
- **State the distinction explicitly:** their workspace is emergent and
  intra-model; KAINE's is an explicit architectural workspace across modules. The
  citation SHALL NOT imply the result validates KAINE's design.
- **Optional careful bridge:** note that the "verbalizable representations" they
  identify are conceptually adjacent to KAINE's internal speech and to the
  reportability criterion the architecture already engages — as a conceptual
  connection, not an equivalence.

## Capabilities

### New Capabilities

- `research-positioning`: a documentation requirement governing how the paper
  situates KAINE relative to the emergent-workspace literature — cite it as
  related work / motivation, with the emergent-intra-model vs
  explicit-architectural distinction stated, and without implying validation.

## Impact

- **Repo:** the predictive-workspace paper repository only (`paper.md` + the
  reference list). No runtime code; no kaine-repo source change beyond this
  OpenSpec record.
- **Depends on:** nothing shipped changes. Relates conceptually to `syneidesis`
  (the architectural workspace) and `lingua` (internal speech), but modifies no
  capability's behavior.
- **Review:** review-before-publishing — the wording is read by the lead before it
  is committed to the paper, like all public-facing paper content.
- **Honest limit (load-bearing):** the two "workspaces" are different constructs;
  the paper must not let the citation read as empirical validation of KAINE's
  architecture.
