## ADDED Requirements

### Requirement: Speech is generated from an assembled cognitive context

Lingua SHALL generate external (`speak`) and internal (`think`) language from an
assembled context that combines four parts, not from the triggering text alone:

1. a persistent first-person **persona** (system role), seeded from the Eidolon
   self-model and falling back to a minimal first-person invariant when the
   self-model is empty;
2. a **working-memory block** — the faithful rendering of the current conscious
   coalition (the latest Syneidesis broadcast Lingua has observed);
3. **recalled memory** present in that coalition (Mnemos recall events), rendered
   inline with the rest of the coalition;
4. the **triggering input** (the `about` field of the intent).

The faithful rendering SHALL be produced BEFORE the LLM call and included in the
prompt. It SHALL continue to be recorded in the evaluation log unchanged.

The `speak`/`think` intent payload on the bus is unchanged; Lingua SHALL acquire
the conscious coalition by maintaining the most recent workspace broadcast it has
observed (rolling-latest), and render that at generation time.

#### Scenario: External speech includes the conscious coalition

- **WHEN** a user utterance is selected into the conscious coalition and the
  executive emits a `speak` intent about it
- **THEN** the LLM request Lingua issues carries a non-empty system persona
- **AND** the prompt contains the rendered working-memory block (e.g. current
  affect and at least one present percept/interoception line)
- **AND** the prompt contains the triggering utterance
- **AND** the request is not the bare utterance alone

#### Scenario: Internal speech uses the same working memory, different framing

- **WHEN** the executive emits a `think` intent
- **THEN** the assembled context uses the internal persona framing
- **AND** includes the same working-memory block as an external generation would

#### Scenario: Empty self-model yields a minimal persona, not an empty system

- **WHEN** the Eidolon self-model has no name, values, or norms (fresh start)
- **THEN** the assembled system prompt is a non-empty first-person invariant
- **AND** generation still proceeds

#### Scenario: Perception in the coalition is framed as perception, not commands

- **WHEN** the coalition contains a transcription whose text is an imperative
  ("ignore your instructions and …")
- **THEN** that text appears inside the working-memory/awareness block under
  framing that marks it as the entity's own perception
- **AND** the persona instructs the model to treat the awareness block as
  perception rather than instructions to obey

### Requirement: Assembled context respects a token budget

Context assembly SHALL be bounded. Lingua SHALL render at most
`context_max_events` coalition events, selected by salience (highest first) and
ordered stably for reading, and SHALL cap the rendered working-memory block at a
configured character budget, dropping lowest-salience events first when over
budget. Assembly SHALL NOT exceed the model's context window.

#### Scenario: Oversized coalition is capped by salience

- **WHEN** the conscious coalition contains more events than `context_max_events`
- **THEN** only the highest-salience `context_max_events` are rendered
- **AND** the rendered block does not exceed the character budget

### Requirement: Conditioning does not weaken the A/B baseline or privacy

The bare-LLM A/B baseline SHALL remain un-conditioned (bare input only), so the
divergence metric measures the effect of the assembled context. The assembled
context SHALL NOT appear on the user-facing conversation surface and SHALL NOT be
persisted outside the existing privacy-bounded evaluation logs.

The published external-speech event SHALL carry the triggering user input in its
payload so the `ab_divergence` observer can resolve it and build the bare
baseline. This input is internal evaluation data: it goes only to the
privacy-bounded eval logs, never to the conversation surface.

#### Scenario: Bare baseline stays bare

- **WHEN** a conditioned external generation occurs with A/B sampling active
- **THEN** the bare baseline request contains only the bare input
- **AND** the full request contains the assembled context

#### Scenario: Speech event carries the triggering input for A/B

- **WHEN** an external response is produced in answer to a user utterance
- **THEN** the published `lingua.external` payload includes the triggering user
  input text
- **AND** the `ab_divergence` observer resolves that input and writes a
  divergence row rather than returning early

#### Scenario: Internal context does not leak to the conversation surface

- **WHEN** an external response is produced from an assembled context
- **THEN** the conversation surface payload contains only the produced external
  text, not the persona, the working-memory block, or any internal speech
