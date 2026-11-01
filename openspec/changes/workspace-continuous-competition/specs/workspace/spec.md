## MODIFIED Requirements

### Requirement: Top-k coalition selection
`Workspace.select` SHALL return a `WorkspaceSnapshot` whose
`selected_events` is the top `top_k` events by salience, ordered
descending, except that with the candidate pool on, eligible overdue
protected members come first as the priority requirement states. The
default `top_k` SHALL be 5 and SHALL be configurable at construction time
and adjustable at runtime via `set_top_k`. With `[workspace.pool].enabled`
true, the cycle SHALL build the workspace with `top_k` equal to
`[workspace.pool].capacity` (default 1) and SHALL NOT read
`[workspace].top_k`.

#### Scenario: Top-5 of ten events
- **WHEN** ten events are presented with distinct salience scores
- **THEN** the returned snapshot contains exactly five events in
  descending salience order

#### Scenario: Fewer events than k
- **WHEN** two events are presented with `top_k=5`
- **THEN** the snapshot contains both events without padding

#### Scenario: One access per broadcast with the pool on
- **WHEN** the pool is on with the default capacity and six held members score 0.9, 0.7, 0.6, 0.5, 0.2 and 0.1 with none protected
- **THEN** the snapshot contains only the member scoring 0.9

## ADDED Requirements

### Requirement: A protected member is overdue after the priority wait
With the pool on, a protected member SHALL be overdue when its episode has been pending for at least `[workspace.pool].priority_wait_s` (default 1.0 s) of unpaused entity time, and eligible when its final score reaches the access threshold.

#### Scenario: Not yet overdue
- **WHEN** a boredom drive event scoring 0.4 has been pending 0.6 s and an audition report scores 0.9, with the threshold 0.35
- **THEN** the coalition is the audition report

### Requirement: Overdue protected members take the coalition first
The coalition SHALL take the eligible overdue protected members first, the longest pending first and ties by key name, then the other candidates by score, up to the capacity. A member below the threshold SHALL NOT be placed by this rule, and the snapshot SHALL be inhibited exactly when no candidate reaches the threshold.

#### Scenario: A concern waits no longer than the bound
- **WHEN** a boredom drive event scoring 0.4 has been pending 1.2 s, the threshold is 0.35, and an audition report scores 0.9
- **THEN** the coalition is the boredom event

#### Scenario: Below the threshold the rule does nothing
- **WHEN** an interoceptive alarm scoring 0.2 has been pending 5 s, the threshold is 0.35, and a vision report scores 0.6
- **THEN** the coalition is the vision report and the alarm stays held

#### Scenario: Oldest pending first
- **WHEN** a fatigue event pending 3 s and a restlessness event pending 1.5 s are both eligible and overdue at capacity 1
- **THEN** the coalition is the fatigue event, and the restlessness event is accessed on a later broadcast tick on which it is eligible

#### Scenario: The bound in broadcasts
- **WHEN** all eight protected keys are pending and eligible on every broadcast tick from the time they become overdue, at capacity 1
- **THEN** every key is accessed within eight broadcast ticks of becoming overdue

### Requirement: Novelty is evaluated once per report
With the pool on, the salience strategy SHALL observe a candidate's novelty once, on the first tick it is scored, and SHALL reuse that value on every later tick while the member is held, keyed by its stream-qualified id. The cached value SHALL be dropped when the member leaves the pool.

#### Scenario: A held report keeps its novelty
- **WHEN** a report scored with novelty 1.0 is held for five ticks
- **THEN** its novelty is 1.0 on every tick and the novelty window received one observation of it

### Requirement: A held report is scored with the current gains
On every tick a held member SHALL be scored with that tick's arousal contrast, gains, goal factor, coherence factor and regulation bias, from its own intensity and its cached novelty.

#### Scenario: Arousal rises while a report is held
- **WHEN** arousal rises between two ticks on which the same report is held
- **THEN** its score on the second tick reflects the second tick's contrast

### Requirement: The feedback head observes arrivals only
With the pool on, `Workspace.select` SHALL take the tick's arrivals separately from the candidates, and the feedback head's `observe_candidates` SHALL receive the arrivals only.

#### Scenario: A held report is observed once
- **WHEN** feedback is on and a vision report is held for three ticks
- **THEN** `observe_candidates` received it on its arrival tick only
