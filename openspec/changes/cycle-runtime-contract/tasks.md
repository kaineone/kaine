## 1. Implementation

- [x] 1.1 Forbid `kaine.cycle` for `kaine.modules`, ignoring imports of `kaine.cycle.types`.

## 2. Verification

- [x] 2.1 `lint-imports`: 8 kept. With a test import of `kaine.cycle.gestation` in a module, the contract is broken; before this change it was kept.
- [x] 2.2 `openspec validate cycle-runtime-contract --strict`.
