## ADDED Requirements

### Requirement: The memory coherence probe is validated by a planted ground-truth control

The memory coherence probe SHALL be validated against a planted ground-truth: a
unique fabricated marker the bare language model provably cannot know is stored
into a REAL memory backend (`MnemosCore` over `InMemoryStorage`), and a cognitive
query client that actually `recall`s from that memory and derives its answer from
the retrieved text SHALL be shown to repeat the marker (high `real_accuracy`)
while a bare client with no memory SHALL NOT (low `bare_accuracy`). The control
SHALL prove the advantage comes from RETRIEVAL and not from the fixture
hard-coding the answer: the SAME cognitive client, when its memory is emptied,
SHALL no longer repeat the marker. The control SHALL keep `kaine.evaluation` free
of `kaine.modules.*` imports — the real memory is constructed at the test level
and the retrieval client is duck-typed against the `CognitiveQueryClient`
protocol.

#### Scenario: Full system retrieves a planted fact the bare model cannot

- **WHEN** a unique fabricated marker is stored into a real `MnemosCore` and the
  probe runs the memory-augmented cognitive client against the bare client
- **THEN** the cognitive client `recall`s the marker and its answer contains it,
  yielding `real_accuracy` above a high floor
- **AND** the bare client (no memory) does not produce the marker, yielding
  `bare_accuracy` below a low floor
- **AND** the recorded `advantage` (`real_accuracy - bare_accuracy`) is positive

#### Scenario: The advantage is retrieval, not a hard-coded answer

- **WHEN** the SAME cognitive client is pointed at an EMPTY `MnemosCore` and asked
  the same question
- **THEN** it no longer repeats the planted marker (its answer is derived from
  what memory returns, which is now nothing)
- **AND** its accuracy drops, demonstrating the positive control's advantage was
  produced by retrieval rather than by the fixture hard-coding the answer

### Requirement: The memory coherence probe reports non-recall without confabulation false positives

When the queried fact was never stored, the memory coherence probe SHALL report
failure-to-recall (accuracy `0.0`) and SHALL NOT report a false positive from a
confabulated non-empty answer. A retrieval client that finds nothing in memory
SHALL emit a non-recall sentinel (`NON_RECALL_MARKER`) rather than confabulate,
and `score_async` SHALL score that sentinel as exactly `0.0`. This honest
non-recall mechanism distinguishes "memory absent → said so" from "memory absent
→ invented an answer," so a confabulation can never be credited as a recall.

#### Scenario: Never-stored fact reports non-recall, not a false positive

- **WHEN** the probe queries for a fact that was never planted into memory
- **THEN** the retrieval client finds nothing and emits the non-recall sentinel
- **AND** the probe records `real_accuracy == 0.0` (failure-to-recall), not a
  positive score from a confabulated answer

#### Scenario: The scorer credits the non-recall sentinel as zero

- **WHEN** `score_async` is given the non-recall sentinel as the response against
  any ground-truth memory
- **THEN** it returns exactly `0.0`, regardless of any incidental lexical overlap
  between the sentinel text and the memory text
