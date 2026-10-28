## ADDED Requirements

### Requirement: A realization failure during shutdown is logged as one line
When a speak or think realization fails after the cycle's stop event or the module's own stop flag is set, the language module SHALL log one WARNING line naming the intent kind and the exception class, with no traceback. When it fails while the system is running, the module SHALL log ERROR with the traceback. In both cases the module SHALL write the content-free `realization_failed` record.

#### Scenario: The model server goes away during shutdown
- **WHEN** the cycle's stop event is set and an in-flight think request then raises a connection error
- **THEN** one WARNING line names `think` and `ConnectionError`, no ERROR record and no traceback is logged, and one `realization_failed` record is written

#### Scenario: A failure while running
- **WHEN** a think request raises while the stop event is not set
- **THEN** an ERROR record with the traceback is logged and one `realization_failed` record is written
