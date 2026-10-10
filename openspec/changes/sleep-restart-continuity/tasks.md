## 1. Thymos

- [x] 1.1 `affective_reset()` clears the error means, alert-rate averages, intent rate and counter, and perceived emotion; keeps wellness and interaction history.
- [x] 1.2 The peer consumer logs and skips an event whose handling raises.
- [x] 1.3 The constructor comment no longer names `social_drive_time_scale_s`.

## 2. Chronos

- [x] 2.1 Each interval is clipped to ten times the window mean before it enters the window; the step's timespan uses the raw interval, capped at 10.
- [x] 2.2 Serialize the time since the last interaction; restore `last_interaction_at` from it; clamp a legacy timestamp to the current time.

## 3. Soma

- [x] 3.1 Correct the slot 7 comments.

## 4. Tests

- [x] 4.1 Valence stays near baseline for 30 s after a reset that follows strong learning progress.
- [x] 4.2 After one 600 s gap, the next normal interval's timespan is close to 1.
- [x] 4.3 A restored Chronos reports the saved time since the last interaction, not 0.
- [x] 4.4 A peer event whose handling raises does not stop later events from being handled.
