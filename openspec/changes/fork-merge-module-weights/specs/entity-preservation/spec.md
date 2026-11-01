## ADDED Requirements

### Requirement: Weight-bearing module state merges only by an explicit choice
Each stock module whose serialized state holds learned parameters SHALL declare a weight group: those keys and the seeds, layouts and encoder ids they were trained against. When both parents carry a module's group and the values differ, merge SHALL refuse, naming the modules, unless the caller passes `module_weights_from` naming a parent for each. The group SHALL then be copied whole from that parent, never merged by the module's strategy.

#### Scenario: No choice
- **WHEN** two snapshots whose vision forward models differ are merged without `module_weights_from`
- **THEN** merge refuses, names `vision`, and writes no merged snapshot

#### Scenario: The chosen parent's weights, exactly
- **WHEN** they are merged with `module_weights_from = "b"`
- **THEN** the merged vision `forward_model` equals parent b's exactly, with the same number of layers

#### Scenario: Weights travel with their reservoir
- **WHEN** two snapshots whose interoception readouts and reservoir seeds differ are merged with `module_weights_from = "a"`
- **THEN** the merged interoception state holds parent a's readout, reservoir seed, feature layout and expected-error statistics

### Requirement: Equal or one-sided weight groups need no choice
A weight group that is deeply equal in both parents, or present in only one parent's state, SHALL be copied without a choice. The merged snapshot's metadata SHALL record, per module with a group, the parent its group came from and whether it was chosen, equal or one-sided.

#### Scenario: Siblings that never trained apart
- **WHEN** two forks of one snapshot with identical forward models are merged without `module_weights_from`
- **THEN** merge succeeds and the metadata records the vision group as equal

### Requirement: A failing strategy for a weight-bearing module refuses the merge
When a module's merge strategy raises and the module has a weight group, merge SHALL raise, naming the module, and SHALL NOT take either parent's state in its place.

#### Scenario: A strategy error
- **WHEN** the merge strategy for interoception raises
- **THEN** merge raises, names interoception, and writes no merged snapshot

### Requirement: Restore refuses a structurally different weight state
A processor's restore SHALL discard, with a warning naming the module and the mismatch, a forward-model state whose number of layers or weight shapes differ from the running model, and SHALL keep the rest of the module's restored state.

#### Scenario: A concatenated vision state
- **WHEN** a vision state holds four layers for a two-layer network
- **THEN** the forward model starts fresh with a warning naming vision and the layer counts

#### Scenario: A mis-shaped interoception readout
- **WHEN** an interoception state holds a 16-row readout for an 8-feature model
- **THEN** the readout starts fresh with a warning, and the module's other restored fields are kept

### Requirement: Every weight-like module state is declared
A test SHALL serialize every stock module entity-free and fail when a module without a specialised merge strategy holds a nested numeric list, or a list of 16 or more numbers, under a top-level key that is neither in its weight group nor in a reviewed non-weight set.

#### Scenario: An undeclared weight key
- **WHEN** a module starts serializing `decoder` as a list of weight rows without declaring it
- **THEN** the test fails and names the module and `decoder`
