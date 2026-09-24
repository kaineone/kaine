## ADDED Requirements

### Requirement: Module restarts keep oscillators continuous
When Spot restarts a module, the module SHALL keep the oscillator it had, with its phase history. On the heavy restart path the rebuilt module SHALL receive the same oscillator object its predecessor held, before it is initialized and registered. A restart SHALL NOT replace or rebuild the oscillator of any other module. A plugin-supplied oscillator SHALL therefore be requested once per declared seam, at boot, and never re-requested by a restart.

#### Scenario: Heavy restart keeps the module's oscillator
- **WHEN** a module with an oscillator is rebuilt on Spot's heavy restart path
- **THEN** the rebuilt module holds the same oscillator object as before, and its phase history is intact

#### Scenario: Other modules are untouched
- **WHEN** one module is restarted
- **THEN** every other module holds the same oscillator object it held before the restart

#### Scenario: Plugin oscillator is not re-requested
- **WHEN** a plugin supplies the oscillator for a module and that module is rebuilt twice
- **THEN** the plugin's `make_oscillator` was called once, at boot, and the module never reports the neutral phase because of the restarts
