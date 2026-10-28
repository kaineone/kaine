## Why

The duplicate-name guard from boot-identity-dedup (#589) checks only module-level functions and classes. Merging main into nexus-welfare-rest (#583) auto-merged two branches that each added `observe` and `backfill` to `ConversationState`. The class then defined both methods twice, the later copies silently replaced the earlier ones, and 19 tests failed. Nothing caught the duplicate itself.

## What Changes

- The guard also checks each class body under `kaine/`, at any depth, for a method name defined more than once. A property with its setter or deleter (same name, decorated with `@<name>.setter` or `@<name>.deleter`) and `typing.overload` stubs are allowed. Definitions in different branches of an `if` or `try` stay exempt, as at module level.
- Nested functions defined twice in the same function body are reported the same way.

## Capabilities

### Modified Capabilities

- `architecture-boundaries`: a class defines each method name once.

## Impact

- `tests/test_no_duplicate_definitions.py`.
- Behaviour: none at run time. A merge that duplicates a method fails the test suite.
