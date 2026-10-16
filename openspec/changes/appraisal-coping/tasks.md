## 1. Implementation

- [x] 1.1 Count each drive's crossing ends by the entity's own response and any other way (relief source and a counterfactual tick step), persist the counts, and expose the success ratio
- [x] 1.2 Count completed and abandoned goals in the goal ledger
- [x] 1.3 Gate coping on a goal score above 0, compute `2p - 1` from the term that sets the goal score, publish `coping_available`, and make `classify()` skip fear, anger and sadness when coping is unavailable
- [x] 1.4 Docs and tests: idle content leaves coping unavailable; the ratio follows own and other ends, including external relief and a held-down build input; ledger outcomes supply power when the ledger sets the score; counts survive serialize and deserialize
