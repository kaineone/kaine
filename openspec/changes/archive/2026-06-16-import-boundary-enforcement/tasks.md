# Tasks (design-first proposal — implement on approval)

## 1. Contracts
- [x] 1.1 Add `import-linter` as a dev dependency (dev/CI only — never in the entity runtime deps).
- [x] 1.2 Author the contracts config: the sidecar-boundary forbidden contract (only the two `__main__` entrypoints may import `kaine.evaluation`) plus the broader real layering (modules ⊥ cycle-runtime, evaluation ⊥ nexus internals, the boundary-neutral shared homes depend on neither side). Confirm it PASSES on current main (the boundary is clean).

## 2. Fast enforcement
- [x] 2.1 Pre-commit hook running the linter (seconds).
- [x] 2.2 A dedicated lightweight CI job (separate from the full pytest) so violations fail fast with a precise message.
- [x] 2.3 Keep the existing grep boundary test as belt-and-suspenders (or fold it into the contract + a thin pytest wrapper so a contract violation still fails pytest).

## 3. Docs
- [x] 3.1 Short architecture doc: the layers, the two allowed seams, and the shared-primitive homes (`kaine/persistence`, `kaine/experiment`, `kaine/privacy_filter`, neutral `kaine/lifecycle`), with the rule "core never imports kaine.evaluation; cross-cutting primitives go to a neutral home."

## 4. Validate
- [x] 4.1 Linter green on current main; full suite still green; `openspec validate --strict`.
