## 1. Implementation

- [x] 1.1 Give the research observer a start-at-tail option that reads each stream's newest entry id when the observer starts, and set it from the sidecar registry
- [x] 1.2 Tests: entries present before start are not recorded and entries published after start are; the registry builds the observer with the option on; the backlog default is unchanged
