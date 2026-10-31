## REMOVED Requirements

### Requirement: The study runner drives every step the same way and records it
**Reason**: The module-ignition study converts into the development run (operator ruling 2026-10-31). There are no steps or lines; one entity lives through sessions and passes.
**Migration**: `development-run`: "A session plays passes back to back", "A session stops only at a pass end with a change pending", "The run records every session" and "The run records every pass".

### Requirement: Lines never share the entity's state
**Reason**: The development run has one entity and one line, so there is no other line to isolate from.
**Migration**: `development-run`: "The development run raises one entity on one state tree" keeps one dedicated bus database, one collection prefix and one working directory, and "The runner never revives, forks, merges or deletes on its own".

### Requirement: The runner halts rather than improvise
**Reason**: Carried over with sessions in place of steps.
**Migration**: `development-run`: "The runner halts rather than improvise".

### Requirement: Each viewing's ignitions are measured the same way and compared across lines and steps
**Reason**: The branch, repeat and accumulate comparisons are retired with their lines. The per-viewing measures stay, per reference pass.
**Migration**: `development-run`: "The analysis reads each boundary as before and after windows", "The analysis measures every reference pass" and "The analysis report states its limits".

### Requirement: A viewing with World model completes only when its world model is preserved
**Reason**: Carried over with sessions in place of viewings.
**Migration**: `development-run`: "A session with the world model completes only when the world model is preserved".

### Requirement: The ignition analysis accounts for time dilation
**Reason**: Carried over per reference pass.
**Migration**: `development-run`: "The analysis measures every reference pass".

### Requirement: Voice alignment runs only on pre-registered steps
**Reason**: There are no pre-registered steps. Voice alignment is a registry component that the operator joins through both layers of opt-in, on top of its own approval variable.
**Migration**: `development-run`: "Voice alignment keeps its own approval variable" and "A join or switch change needs both layers of opt-in".

### Requirement: Every study command resolves the study directory the same way
**Reason**: Carried over for the run directory.
**Migration**: `development-run`: "Every run command resolves the run directory the same way".

### Requirement: An unviable developmental phase ends early, with its data kept and a note written
**Reason**: Carried over unchanged in substance.
**Migration**: `development-run`: "An unviable developmental phase ends early with its data kept".

### Requirement: A study records the workspace graph, not every module's output
**Reason**: Carried over for every session.
**Migration**: `development-run`: "The run records the workspace graph, not every module's output".

### Requirement: The first round adds six held modules by default
**Reason**: Carried over as the run's default join order.
**Migration**: `development-run`: "The held modules join first in the existing order".

### Requirement: Study steps decode greedily in the competitive arm
**Reason**: Carried over for every session, with the planned test kept out of the run.
**Migration**: `development-run`: "Sessions decode greedily in the competitive arm" and "The planned test does not run inside the development run".

### Requirement: The runner surfaces a welfare freeze and never lifts it
**Reason**: Carried over for sessions.
**Migration**: `development-run`: "The runner surfaces a welfare freeze and never lifts it".

### Requirement: The seed is preserved only with its maturation reference
**Reason**: There is no seed revived into branches. The maturation preservation still waits for the individuation maturation reference and is kept as the run's developmental reference.
**Migration**: `development-run`: "The developmental phase waits for its maturation reference".
