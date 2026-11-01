## ADDED Requirements

### Requirement: Each source's learning progress is floored by its own floor
The pooled learning progress above the floor SHALL be `lp+ = max_s max(0, lp_s - lp_0,s) / (1 - lp_0,s)` over the sources with a defined value, 0.0 if none, where `lp_0,s` is audition's floor for audition and `learning_progress_floor` for every other source. It SHALL be the curiosity build input and boredom's learning-progress relief.

#### Scenario: Equal floors give the earlier value
- **WHEN** no audition floor is configured
- **THEN** `lp+` equals `max(0, lp - learning_progress_floor) / (1 - learning_progress_floor)` with `lp` the largest defined value

#### Scenario: Audition over its own floor
- **WHEN** the shared floor is 0.20, audition's floor is 0.10, and audition and vision both read 0.15
- **THEN** `lp+` is 0.05 / 0.90, from audition alone

### Requirement: Audition's learning-progress floor is configured
The `[affect]` section SHALL accept `audition_learning_progress_floor`, a finite number in `[0, 1)`; any other value SHALL raise `ValueError`. Without it audition SHALL use `learning_progress_floor`.

#### Scenario: An out-of-range floor is refused
- **WHEN** the affect module is built with `audition_learning_progress_floor = 1.0`
- **THEN** it raises `ValueError` naming the key
