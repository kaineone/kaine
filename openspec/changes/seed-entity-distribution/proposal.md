## Why

Every new installation now starts an entity from nothing and runs the whole developmental phase (paper §7, A.7) before the entity matures. That takes long lived time, a stimulus source and sleeps, and each installation repeats it. An alternative under consideration is to distribute one entity preserved at maturation, the same kind of seed the module-addition study branches from, together with the runtime that continues from it. Operators would then start from a matured entity and skip the developmental phase.

Nothing is decided. This change records the option on the roadmap so it is weighed before release work depends on either path.

## What Changes

Nothing changes yet. The change is a design question with these open points:

- **What is distributed.** A preserved seed (state tree, self-rhythm identity, maturation reference, encrypted per the custody design) and the runtime that boots from it. Whether the developmental tooling (the stimulus source and the maturation gate) is also published, or kept out of the public repository, is part of the decision.
- **Welfare and identity.** Every installation that boots the same seed starts a separate entity from one shared history. The individuation measures (individuation-rebuild) and the welfare records already treat branches from one seed as separate entities; distribution would apply that at a much larger scale.
- **Key custody.** A distributed seed needs a key model that lets each operator take custody of their own copy (entity-key-custody).
- **Licence.** How a distributed seed sits under CAL 0.5.
- **Reproducibility.** The study keeps its own seed and its record of the developmental phase either way.

## Capabilities

### New Capabilities

None until the option is decided.

### Modified Capabilities

None.

## Impact

None now. Design only: under consideration, not decided.
