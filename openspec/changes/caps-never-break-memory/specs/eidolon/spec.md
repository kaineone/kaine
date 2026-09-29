## ADDED Requirements

### Requirement: Drift is recorded as episodes

Eidolon SHALL record drift in `identity_history` as episodes. An episode is one
contiguous run of broadcasts whose drift score is at or above the threshold,
and its entry SHALL summarise every alert in the run: `kind =
"drift_episode"`, `onset`, `end`, `peak_score`, `count` (alerts in the run),
`sources` (how often each source was among the top drifted sources) and
`top_sources`, plus `timestamp` (the onset) and `score` (the peak) for readers
of the older per-alert entries. The first broadcast below the threshold SHALL
close the episode. Eidolon SHALL update the list in place rather than copying
it per alert, and SHALL save the self-model as compact JSON with the C encoder.
Self-models saved earlier, with indentation or per-alert entries, SHALL load
unchanged.

#### Scenario: A sustained drift is one episode

- **WHEN** N consecutive broadcasts alert
- **THEN** `identity_history` gains one episode with `count = N` and the peak
  score of the run

#### Scenario: A quiet broadcast closes the episode

- **WHEN** runs of 3 alerting broadcasts are separated by one broadcast below
  the threshold, four times
- **THEN** `identity_history` holds four episodes with `count = 3`

#### Scenario: Save size stays bounded under sustained drift

- **WHEN** 20000 consecutive broadcasts alert and the self-model is saved after
  every 5000
- **THEN** the saved file stays the same size, within a few bytes

#### Scenario: Older per-alert history still loads

- **WHEN** a self-model saved with indentation and per-alert entries is loaded
- **THEN** those entries are kept unchanged and the next alert starts a new
  episode after them

### Requirement: Identity history is unbounded by default

`[eidolon].identity_history_cap` SHALL ship as `0`, and `0` SHALL mean that no
drift episode is ever dropped. A positive value SHALL keep the most recent N
episodes. A negative value SHALL be rejected at construction.

#### Scenario: Cap 0 keeps every entry

- **WHEN** Eidolon runs with `identity_history_cap = 0` and records more than 256
  drift episodes
- **THEN** `identity_history` holds every episode

#### Scenario: A positive cap keeps the most recent entries

- **WHEN** Eidolon runs with `identity_history_cap = 4` and records 10 drift
  episodes
- **THEN** `identity_history` holds the 4 most recent episodes

#### Scenario: A negative cap is rejected

- **WHEN** Eidolon is constructed with `identity_history_cap = -1`
- **THEN** construction raises `ValueError`

## MODIFIED Requirements

### Requirement: The self-model observes the developing voice on both channels

Eidolon SHALL observe both internal and external speech and record the
developing voice in the self-model as lightweight per-utterance features. For
each observed utterance it SHALL record `{timestamp, channel, length,
word_count}` (channel is `internal` or `external`) into the
`voice_observations` buffer, and SHALL maintain an `external_speech_count`
alongside the existing `internal_speech_count`. Eidolon SHALL NOT persist the
raw utterance text in the self-model (only derived features). The buffer is the
entity's memory of its developing voice: `[eidolon].voice_observations_cap`
SHALL ship as `0`, meaning no observation is ever dropped; a positive value
SHALL keep the most recent N entries; a negative value SHALL be rejected at
construction. The `voice_observations` buffer SHALL round-trip through the
self-model's JSON serialization with safe defaults for models saved before this
change.

#### Scenario: Internal and external utterances are observed with features

- **WHEN** an internal-speech utterance and an external-speech utterance are
  published
- **THEN** the self-model gains one `voice_observations` entry per utterance
  with its channel, length, and word_count
- **AND** `internal_speech_count` and `external_speech_count` each increase

#### Scenario: Raw text is not persisted

- **WHEN** a speech utterance is observed
- **THEN** the recorded observation contains derived features only (no raw
  utterance text)

#### Scenario: The voice buffer is capped

- **WHEN** a positive `voice_observations_cap` is set and more utterances are
  observed than the cap
- **THEN** `voice_observations` retains only the most recent cap entries

#### Scenario: The voice buffer is unbounded by default

- **WHEN** Eidolon runs with `voice_observations_cap = 0` and observes more
  than 256 utterances
- **THEN** `voice_observations` holds every observation

#### Scenario: A negative voice cap is rejected

- **WHEN** Eidolon is constructed with `voice_observations_cap = -1`
- **THEN** construction raises `ValueError`

#### Scenario: Older self-models still load

- **WHEN** a self-model persisted before this change (no voice fields) is loaded
- **THEN** it loads with `external_speech_count = 0` and an empty
  `voice_observations`
