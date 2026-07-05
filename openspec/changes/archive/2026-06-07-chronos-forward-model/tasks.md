## 1. Forward prediction

- [x] 1.1 Add a prediction head to the Chronos CfC predicting the next temporal feature vector from the hidden state
- [x] 1.2 Online adaptation step per tick (small LR); suspend during Hypnos; non-finite guard

## 2. Salience

- [x] 2.1 Drive anomaly salience from `temporal_prediction_error`; retain z-score `anomaly_score`, `habituation_score`, `rumination_detected` on the payload

## 3. Module + config

- [x] 3.1 Wire prediction head into `Chronos`; `serialize()`/`deserialize()` persist head weights
- [x] 3.2 `[chronos]` config: `forward_prediction`, `prediction_error_window`; update `make_chronos` allowed keys

## 4. Tests

- [x] 4.1 `tests/test_chronos_network.py` — prediction head shape; error drops on a regular cadence
- [x] 4.2 `tests/test_chronos_module.py` — `temporal_prediction_error` on report; anomaly salience tracks error; habituation/rumination retained; serialize roundtrip

## 5. Verification

- [x] 5.1 Full unit suite green
- [x] 5.2 `openspec validate chronos-forward-model --strict` clean
- [x] 5.3 Commit (Kaine.One), branch-per-change, merge, archive
