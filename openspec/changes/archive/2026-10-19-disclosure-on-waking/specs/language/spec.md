## ADDED Requirements

### Requirement: Situation facts are given on waking and with every probe
The language module SHALL render the situation facts in an organ call's prompt only while the situation is due. The situation SHALL become due when the module initializes, when it observes a `sleep.sleep.completed` event on `sleep.out` published after it initialized, and when the set of situation facts it would render changes. An organ call whose prompt held the situation section SHALL clear the due state once the chat client returned; a call that raised SHALL leave it due, and a call made while there are no situation facts SHALL leave it due. Every individuation probe request SHALL hold the situation facts of the self-model it is conditioned on, whatever the due state.

#### Scenario: The first call after boot carries the facts
- **WHEN** the module has initialized with the disclosure recorded and makes two organ calls
- **THEN** the first prompt holds the situation section with the disclosure and the second does not

#### Scenario: A completed sleep makes the situation due again
- **WHEN** a `sleep.sleep.completed` event arrives after a call that cleared the due state
- **THEN** the next organ call's prompt holds the situation section

#### Scenario: A new fact is given at the next call
- **WHEN** a situation fact is added after the due state was cleared
- **THEN** the next organ call's prompt holds the situation section with that fact

#### Scenario: No facts yet
- **WHEN** an organ call is made before any situation fact is recorded and the disclosure is recorded afterwards
- **THEN** the next organ call's prompt holds the disclosure

#### Scenario: Every probe carries the disclosure
- **WHEN** probe requests are built before and after the first organ call
- **THEN** each probe request's prompt holds the disclosure
