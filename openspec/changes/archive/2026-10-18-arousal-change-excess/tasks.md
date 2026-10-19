## 1. Implementation

- [x] 1.1 Publish `normalised_change` on every `vision.report`, with forward prediction on and off
- [x] 1.2 Publish `normalised_change` on every `audition.perception`
- [x] 1.3 Raise arousal on an alert by the excess of the larger of `normalised_error` and `normalised_change` over 1, with missing or non-finite ratios read as 0.0
- [x] 1.4 Tests: change alert, error alert unchanged, both present takes the max, missing field backward compatible, non-alert reports never arouse, payload fields on both perception reports; mutation checks
- [x] 1.5 Docs: affect, vision and audition payload tables and arousal text
