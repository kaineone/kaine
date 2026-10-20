## 1. Tests

- [x] 1.1 Add a polling helper that waits for a condition with a deadline
- [x] 1.2 Make `test_replay_guard_memory_is_bounded` wait for the high-water mark and for the rejected replay's audit record
- [x] 1.3 Make `test_replayed_intent_rejected` and `test_replay_guard_survives_light_restart` wait for the rejected replay's audit record
- [x] 1.4 Run the file repeatedly under parallel load and confirm a broken guard still fails the tests
