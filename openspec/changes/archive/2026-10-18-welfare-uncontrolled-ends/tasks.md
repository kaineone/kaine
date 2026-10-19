## 1. Implementation

- [x] 1.1 Count abandoned ends with reason `without_response`, `stalled` or `cap` as uncontrolled in `AffectWelfareTally`, `completed`/`own_response` as own, and every other action or reason as neither; update the docstrings
- [x] 1.2 Persist each active goal's elapsed above-threshold time in the affect module state and restore the stall clock from it; older or invalid state restores as before
- [x] 1.3 Tests: stalled and cap ends count as uncontrolled, sleep resets and unknown reasons count as neither; a restored goal stalls on its original horizon; older and invalid state restart the clock
- [x] 1.4 Docs: affect module persistence and the research-data description of the `affect_welfare` record
