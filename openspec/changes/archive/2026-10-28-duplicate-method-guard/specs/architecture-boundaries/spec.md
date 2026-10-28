## ADDED Requirements

### Requirement: A class defines each method name once
No class under `kaine/`, at any nesting depth, SHALL define the same method name more than once, and no function SHALL define the same nested function name more than once, apart from one definition in each branch of a conditional, a property's getter with its setter or deleter, and `typing.overload` stubs. A test SHALL check this over the package.

#### Scenario: A duplicated method
- **WHEN** a class under `kaine/` defines `observe` twice
- **THEN** the test fails and names the module, the class, the method and both line numbers

#### Scenario: A property setter
- **WHEN** a class defines a property and its setter under the same name
- **THEN** the test passes
