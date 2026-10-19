## 1. Implementation

- [ ] 1.1 `extract`: decrypt the intent log and system-prompt store into cases, skipping placeholder records
- [ ] 1.2 Variant transforms V0, V1, V2, V3, V123 and the raw text, as pure functions
- [ ] 1.3 `run`: replay through the language client's request shape and the sentence cut; raw completion through `/completion`
- [ ] 1.4 `score`: classifiers, cluster-bootstrap intervals and the fixed decision rule
- [ ] 1.5 Tests for the transforms, classifiers and decision rule; README row
- [ ] 1.6 Run the comparison on the ninth test boot's intent log and record the table in the PR
