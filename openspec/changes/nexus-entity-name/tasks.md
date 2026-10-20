## 1. Implementation

- [ ] 1.1 Add observers to the bus bridge, called for every event read before the privacy filter, with a raising observer logged and skipped
- [ ] 1.2 Add `ConversationState.observe`, the start-up name reader (self-model file, then the identity file's optional `name`) and the bus backfill through a new `AsyncBus.recent`
- [ ] 1.3 Wire the state into the dashboard entrypoint and the app lifespan, and show the name and the server's sleep state on the console
- [ ] 1.4 Tests: observer delivery with and without clients, a raising observer, name sources and their fallbacks, the backfill, the rendered title and rail, and the chip's start state in a JavaScript harness
- [ ] 1.5 Document the name and the chip's start state in docs/05-dashboard.md
