## ADDED Requirements

### Requirement: Recalled content renders as remembered
A felt recall line with `content` SHALL begin "I remember" followed by the age phrase for its band ("from earlier today" for `this_wake`, "from before my last rest" for `last_wake`, "from long ago" for `earlier`) and the members' past-tense lines. A member whose type has no past-tense template SHALL render as "I remember a moment I cannot make out." No recalled line SHALL use a present-tense perceptual template, and the line SHALL contain no digit outside quoted own words.

#### Scenario: A recalled vision report is in the past tense
- **WHEN** a recall's content holds an accessed vision report graded sudden and new, band `last_wake`
- **THEN** the line reads "I remember, from before my last rest: what I saw was sudden and new to me."

#### Scenario: An unknown member type is not invented
- **WHEN** a recall's content holds a member of a type with no past-tense template
- **THEN** that member renders as "I remember a moment I cannot make out."

### Requirement: A recall without content renders familiarity
A felt recall line without `content` and with a count above zero SHALL grade familiarity from `top_similarity` by its rank among the last `familiarity_window` recalls, default 100: lowest third "This feels faintly familiar.", middle third "This feels somewhat familiar.", top third "This feels familiar." With fewer than ten earlier recalls it SHALL be "This feels somewhat familiar." A count of zero SHALL render "Nothing comes back to me from memory."

#### Scenario: A high similarity among recent recalls
- **WHEN** a recall without content has the highest `top_similarity` of the last 100 recalls
- **THEN** it renders "This feels familiar."

#### Scenario: Nothing returned
- **WHEN** a recall returns no trace
- **THEN** it renders "Nothing comes back to me from memory."

### Requirement: No recall line implies content it does not carry
The renderer SHALL NOT produce "Some memories come back to me." or any recall line that refers to remembered content unless the event carries `content`.

#### Scenario: The old sentence is gone
- **WHEN** every recall template is rendered over payloads with and without `content`
- **THEN** no output equals "Some memories come back to me." and only outputs from payloads with `content` begin "I remember"

### Requirement: Replay with members renders its content
A felt replay line for a trace with `members` SHALL read "As I rest, I go over a memory:" followed by the accessed members' past-tense lines, at most `recall_render_max`. A replay of a trace without `members` SHALL stay "I am going over a memory."

#### Scenario: Replay of a trace with an own thought
- **WHEN** a replayed trace's accessed member is a language thought with text "the light keeps changing"
- **THEN** the replay line contains "As I rest, I go over a memory:" and "the light keeps changing"
