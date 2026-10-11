## ADDED Requirements

### Requirement: A long pause does not distort later reservoir steps
Before an interval between broadcasts enters the window that sets the mean interval, Chronos SHALL clip it to ten times the mean of the intervals already in the window. The step that follows the pause SHALL still use the raw interval over the window mean, capped at 10.

#### Scenario: Normal steps resume after a pause
- **WHEN** broadcasts arrive 0.2 s apart, then one arrives after a 600 s pause, then they resume 0.2 s apart
- **THEN** the step after the pause has a timespan of 10, and the next normal step's timespan is between 0.5 and 1.5
