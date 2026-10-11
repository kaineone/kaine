## 1. Implementation

- [x] 1.1 Suspend perception at sleep start and restore it in a `finally` at sleep end in `enter_sleep`
- [x] 1.2 Stop phase 2 from suspending and restoring perception
- [x] 1.3 Tests: without Mnemos the locus is `off` during sleep and restored after; restore also runs when the pipeline raises or is cancelled
