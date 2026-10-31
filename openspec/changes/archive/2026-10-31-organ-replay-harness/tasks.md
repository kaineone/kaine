## 1. Implementation

- [x] 1.1 `extract`: decrypt the intent log and system-prompt store into cases, skipping placeholder records
- [x] 1.2 Variant transforms V0, V1, V2, V3, V123 and the raw text, as pure functions
- [x] 1.3 `run`: replay through the language client's request shape and the sentence cut; raw completion through `/completion`
- [x] 1.4 `score`: classifiers, cluster-bootstrap intervals and the fixed decision rule
- [x] 1.5 Tests for the transforms, classifiers and decision rule; README row
- [x] 1.6 Run the comparison on the ninth test boot's intent log and record the table in the PR
  *Done 2026-10-19: all 190 recoverable organ requests of the ninth test boot, 5 seeds each at temperature 0.7, through the boot's llama.cpp image and GGUF; the table and the fixed decision rule's outcome (adopt V2, reject V3) are recorded in the persona-without-self-category PR.*
