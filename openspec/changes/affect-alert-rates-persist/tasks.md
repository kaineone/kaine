## 1. Implementation

- [x] 1.1 Save and restore the alert rates, the per-source error means, the intent rate, the wellness and the interaction flag in `Affect.serialize()` and `deserialize()`, tolerating state that lacks or garbles them
- [x] 1.2 Test the round trip, the boredom outcome across a restore, and the restore of older state
- [x] 1.3 Update `docs/09-modules/affect.md` and run the affect tests and `tests/test_resume_checkpoint*.py`
