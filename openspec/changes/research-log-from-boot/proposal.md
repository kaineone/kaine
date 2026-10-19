## Why

After the plain restart in the ninth test boot, the research event log re-recorded the whole retained history of every curated stream under the new run's id: about 64 records of each report type, 34 affect states and all 175 intents of the first run, every one stamped within half a minute of the restart. `ResearchEventObserver` inherits the stream observer's default start cursor `"0"`, so a restarted cycle reads the persisted bus streams from their head. Its inner workspace observer already starts at `"$"`, so broadcasts were not replayed, and the rows disagreed with each other. Any per-run count from the log (intents, speech, drive events) double-counts after a restart.

## What Changes

- The curated research observer starts each stream at the stream's newest entry, read when the observer starts. The sidecar starts before the modules launch, so everything this run publishes is still recorded, and nothing a previous run published is.
- The start position is a constructor option; the sidecar registry sets it, and the observer's default stays the backlog read the unit tests use.

## Capabilities

### Modified Capabilities

- `research-event-log`: the log records only the events of the run that writes it.

## Impact

- `kaine/evaluation/observers/research_event_observer.py`, `kaine/evaluation/registry.py`, `tests/test_research_event_log.py`.
- Behaviour: a restarted entity's research log no longer repeats the previous run's records. A first boot is unchanged.
