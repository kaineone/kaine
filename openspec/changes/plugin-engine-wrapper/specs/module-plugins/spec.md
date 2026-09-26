## ADDED Requirements

### Requirement: Nous' engine can be wrapped
A plugin SHALL be able to declare `nous.engine_wrapper` and supply a callable. When Nous is constructed with a wrapper, KAINE SHALL build the default engine from `[nous]` as it does without plugins, call the wrapper with that engine, and use the returned engine. The returned object SHALL satisfy `ActiveInferenceEngine`; otherwise construction SHALL fail with an error naming the plugin.

#### Scenario: Wrapper receives the default engine
- **WHEN** a plugin supplies a wrapper for Nous and `[nous]` sets `planning_horizon = 2`
- **THEN** the wrapper is called with a `PymdpEngine` built with that horizon, and Nous uses the wrapper's return value

#### Scenario: Wrapper returns something that is not an engine
- **WHEN** the wrapper returns an object without `step`
- **THEN** construction fails with an error naming the plugin

### Requirement: Replacement and wrapper are exclusive
Filling both `nous.engine` and `nous.engine_wrapper`, whether by one plugin or by two, SHALL stop the boot with an error naming the plugins involved.

#### Scenario: Both seams declared
- **WHEN** one plugin declares `nous.engine` and another declares `nous.engine_wrapper`
- **THEN** loading the plugins raises an error naming both
