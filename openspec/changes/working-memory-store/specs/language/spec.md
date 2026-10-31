## ADDED Requirements

### Requirement: The notes arm renders held entries after the coalition
With `[working_memory].arm` set to `notes` or `both`, the awareness block SHALL render the current coalition as before and then each held entry not in it, newest first, as its felt line preceded by a recency phrase: "just now" below 2 entity seconds since access, "a moment ago" below 10, "a little while ago" otherwise. The felt prompt SHALL contain no digit outside quoted heard speech.

#### Scenario: A held entry follows the coalition
- **WHEN** a speak is realized with a coalition holding an affect event and the store holding an audition report accessed 4 entity seconds ago
- **THEN** the awareness block holds the affect line and then the audition report's felt line preceded by "a moment ago"

### Requirement: The caps drop held entries before coalition lines
When `context_max_events` or `context_char_budget` binds, the awareness block SHALL drop held entries before coalition lines, oldest held entry first.

#### Scenario: Caps drop held entries first
- **WHEN** the coalition and the store together exceed `context_max_events`
- **THEN** every coalition line is kept and the oldest held entries are left out

### Requirement: A held heard event follows the heard rule
A held entry classified as heard SHALL appear in the awareness block only as the line "Someone else spoke to me." with its recency phrase, and its words SHALL NOT appear in the awareness block, the logged working memory or the numeric log rendering.

#### Scenario: Heard words never enter the notes from the store
- **WHEN** the store holds a heard event whose text is "come here" and a think is realized
- **THEN** the prompt contains no "come here" and holds "Someone else spoke to me." for that entry
