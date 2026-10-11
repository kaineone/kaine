## 1. Null-context evaluation

- [x] 1.1 `BroadcastContext.context_and_null` builds the context and its null from one clock reading; Topos, Audition and Soma use it
- [x] 1.2 Reports carry `null_prediction_error` and `mean_prediction_error`; the research log and the range sweep know them
- [x] 1.3 Soma's forward model clears its null error, prediction, context and hidden state on a skipped non-finite reading, and Soma keeps the skip out of its running mean
- [x] 1.4 Tests: the null replaces only other sources' contributions by their running means; the gain is exactly zero when the context carries nothing; the paired evaluations reproduce the gain; a skipped reading reports no gain
- [x] 1.5 Docs: the module pages and the research-data chapter list the new fields

## 2. Positive control (decided 2026-10-10; built in change `ablation-positive-control`)

- [x] 2.1 Decide what the synthetic component carries for each processor and how it reaches the context before the next input arrives
- [x] 2.2 Decide whether the with and without comparison is within one run or across paired runs
- [x] 2.3 Decide how the control's minimum effect is set
- [x] 2.4 Build the control as a study-mode facility, off by default, with the minimum effect as configuration and a pass or fail record per processor
- [x] 2.5 Tests: the control passes on an informative component and fails on a non-informative one
