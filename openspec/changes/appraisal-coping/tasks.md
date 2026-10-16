## 1. Implementation

- [x] 1.1 Count each drive's crossing ends by relief and by decay alone, persist the counts, and expose the success ratio
- [x] 1.2 Count completed and abandoned goals in the goal ledger
- [x] 1.3 Gate coping on a goal score above 0, compute `2p - 1` from the term that sets the goal score, publish `coping_available`, and make `classify()` skip fear, anger and sadness when coping is unavailable
- [x] 1.4 Docs and tests: idle content leaves coping unavailable; the ratio follows relief and decay ends; ledger outcomes supply power when the ledger sets the score; counts survive serialize and deserialize
