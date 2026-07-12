## Why

The project has been reconfigured to its **base-thesis form** as the default
(the `thesis-test-configuration` change): five predictive-workspace processors
(Soma, Chronos, Topos, Audition, Lingua) competing through Syneidesis, observed
rather than conversed with, perception entering only as prediction error (no STT
transcript path), a self-initiated voice, a reference stimulus corpus for the live
run, and the workspace-mediation ablation as the falsifier — with the richer
faculties built and gated behind a positive result.

The documentation still describes the *prior* framing — "sixteen modules, the mind
is the loop," a conversational/assistant reading, seeded-random stimuli, the A/B
divergence test, and the full set as the active configuration. ~60 public-facing
files are now out of step with the code, the config default, and the project goals.
The README front-door has been reframed (in the base-thesis config change); the
rest is planned here for a dedicated, reviewable docs pass.

## What Changes

Reframe the documentation to the base-thesis form — **content only, no code**:

- **Front-door docs** (`docs/README.md`, `for-researchers.md`, `getting-started.md`,
  `architecture.md`, `configuration.md`, `reproducing-results.md`): lead with the
  base-thesis default (five processors + workspace + voice), the observed-not-chatbot
  stance, perception-as-prediction-error, the self-initiated voice, the reference
  stimulus corpus, and the ablation as the falsifiable test. The richer faculties
  are described as built-and-gated.
- **Module docs** (the 16 under `docs/modules/`): mark which are in the base-thesis
  active set vs. gated; update Audition for the STT-off / acoustic-perception path;
  update Lingua for output-only, self-initiated report (not conversational); update
  Topos for foveated raw video.
- **Reference/top-level** (`ARCHITECTURE.md`, `FIRST_BOOT.md`, `SETUP.md`,
  `docs/deployment-*`, `docs/glossary.md`, etc.): consistency pass — module counts,
  "seeded" → "reference stimulus corpus" for the live tier (keep "seeded" for the
  offline ablation), drop/retire the A/B divergence description, add the
  output-is-provably-workspace-mediated property.

Guardrails: keep the honest posture (falsifiability, necessary-not-sufficient, the
hard problem), stay non-marketing, and treat every file as **public content for
Erik's review before it ships**. The paper is maintained in its own repo and is
handled separately (a paper-agent prompt already exists).

## Capabilities

### New Capabilities
<!-- None: this is a documentation-content change; it modifies no capability
     requirements. The specs of record and the code are the source of truth the
     docs are brought into line with. -->

### Modified Capabilities
<!-- None. -->

## Impact

- **Docs only:** `README.md` (front-door already done), `ARCHITECTURE.md`,
  `FIRST_BOOT.md`, `SETUP.md`, and `docs/**` (~60 files incl. the 16 module docs).
- **No code, no config, no behavior change.**
- **Execution:** tier 1 = the ~6 front-door docs (review the framing), then tier 2 =
  the module docs + the breadth pass, fanned out and reviewed in a batch. Depends on
  `thesis-test-configuration` landing first (the config the docs describe).
