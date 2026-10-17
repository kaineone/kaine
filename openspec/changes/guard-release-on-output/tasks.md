## 1. Implementation

- [x] 1.1 Add `ActionSelection.observe_own_output` and the realization hooks on every guarded policy, with the planning wrapper clearing its local guard and forwarding to the wrapped policy
- [x] 1.2 Forward every organ speech event the cycle engine gathers to `observe_own_output`, on every tick and before selection
- [x] 1.3 Tests: an unaccessed internal or external speech event releases the matching guard so a later accessed crossing produces an intent, the other channel stays armed, the timeout still releases, and the engine forwards unselected organ output; mutation-check the key tests
- [x] 1.4 Docs: the guard release in the workspace, architecture and language pages
