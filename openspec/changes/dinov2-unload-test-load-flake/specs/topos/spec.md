## ADDED Requirements

### Requirement: An encoder unload waits for in-flight inference
A vision module encoder's unload SHALL release its model only after every inference already running in a worker thread has finished, including an inference whose caller was cancelled.

#### Scenario: A cancelled encode is still running in its worker thread
- **WHEN** an encode is cancelled while its forward pass runs in a worker thread and unload is then called
- **THEN** unload does not finish and the model stays loaded until the worker thread returns, after which unload completes and the in-flight count is zero
