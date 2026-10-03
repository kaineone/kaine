## 1. Streams
- [x] 1.1 `diagnostics_streams()` lists `cycle.out` in place of `cycle.tick`; the exclusion comment is corrected.
- [x] 1.2 Guard test: every diagnostics stream is `workspace.broadcast` or a canonical module's output stream; `cycle.out` is present; `cycle.tick` is not.

## 2. Bus decode
- [x] 2.1 The read-path decoder turns a workspace entry into a `workspace.broadcast` event (source, type, payload, timestamp, salience as specified); corrupt snapshots are skipped.
- [x] 2.2 Tests on fakeredis: an entry written by the real `publish_workspace` is read back as that event; a corrupt snapshot is skipped; `subscribe_workspace` is unchanged.
- [x] 2.3 Covered by 2b.2: the real bridge relays a published broadcast and a `cycle.tick` to a client, after the privacy filter.

## 2b. Bridge cursor
- [x] 2b.1 `AsyncBus.last_entry_id(stream)`; the bridge resolves `$` per stream before its first read and retries a failed resolution on the next poll; `_BusLike` gains the method.
- [x] 2b.2 End-to-end test on fakeredis: an entry present before start is not relayed; a module event, a `cycle.tick` and a published broadcast after start all reach a client, filtered (a nested `latent` is removed).

## 3. Charts
- [x] 3.1 Chart routing is a pure function on the page; coherence from broadcasts, salience chart without `cycle`/`syneidesis` events.
- [x] 3.2 Real-browser test of the routing function (system Chrome via Playwright, as the layout test does).

## 4. Docs
- [x] 4.1 Nexus chapter and operation chapter: the rate, salience and coherence chart sources.
