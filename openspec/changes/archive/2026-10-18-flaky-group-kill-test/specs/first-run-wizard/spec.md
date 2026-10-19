## ADDED Requirements

### Requirement: A stopped setup job reports its final status after its output is complete
When the operator cancels a running setup job, or the setup server shuts down
while one runs, the runner SHALL stop the job's whole process group, including
descendants that ignore SIGTERM. The job SHALL then report a final status
(`cancelled` after a cancel, `failed` after a shutdown) once its process has
exited and its output has been fully read.

#### Scenario: Cancelling a job whose descendant ignores SIGTERM
- **WHEN** the operator cancels a job whose child spawned a grandchild that ignores SIGTERM
- **THEN** the grandchild is gone
- **AND** once the job is done its status is `cancelled`

#### Scenario: Shutting down while such a job runs
- **WHEN** the setup server shuts down while that job runs
- **THEN** the grandchild is gone
- **AND** once the job is done its status is `failed`
