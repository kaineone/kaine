## ADDED Requirements

### Requirement: audition.emotion SHALL carry degraded flag when model absent

`Audition` SHALL include `"degraded": true` in the `audition.emotion` event
payload when the emotion classification model is unavailable (funasr not
installed or not yet loaded).  This distinguishes a placeholder result from a
real low-confidence classification and allows downstream consumers to gate on
the flag.

#### Scenario: emotion model absent

- **WHEN** `Audition._publish_emotion()` is called with an `EmotionResult`
  whose `raw` field contains `"degraded": true`
- **THEN** the published `audition.emotion` payload carries `"degraded": true`

#### Scenario: emotion model present

- **WHEN** `Audition._publish_emotion()` is called with a real `EmotionResult`
  (no `degraded` key in `raw`)
- **THEN** the published `audition.emotion` payload does NOT carry `"degraded"`
