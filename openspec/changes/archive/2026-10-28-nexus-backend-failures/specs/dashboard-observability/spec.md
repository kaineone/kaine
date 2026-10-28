## ADDED Requirements

### Requirement: Backend load failures come from the cycle
The cycle SHALL write the content-free records of its runtime-backend load failures (`module`, `backend`, `reason`, `fallback`, `ts`) into `state/cycle/runtime.json` as `backend_failures`, an empty list when every selected backend loaded. The dashboard's `backends` block SHALL report those records together with any recorded in the dashboard's own process, and SHALL carry `source`: `cycle` when the runtime file holds the list, `cycle_not_running` when there is no runtime file, `not_reported` when the file lacks the key. `ok` SHALL be false when any failure is reported, true when the cycle reported an empty list and the dashboard recorded none, and null otherwise. The health board SHALL show the block.

#### Scenario: The cycle fell back
- **WHEN** the cycle recorded that the language module's `llama_cpp` backend failed and `ollama` was used instead
- **THEN** the backends block has `ok` false and that record, and the health board shows it with its fallback

#### Scenario: No cycle running
- **WHEN** there is no runtime file and the dashboard recorded no failure
- **THEN** the block has `ok` null and `source` "cycle_not_running", and the board says the cycle is not running

#### Scenario: Every backend loaded
- **WHEN** the runtime file holds an empty `backend_failures` list
- **THEN** the block has `ok` true and `source` "cycle"
