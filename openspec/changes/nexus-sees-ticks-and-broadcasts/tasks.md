## 1. Streams
- [ ] 1.1 `diagnostics_streams()` lists `cycle.out` in place of `cycle.tick`; the exclusion comment is corrected.
- [ ] 1.2 Guard test: every diagnostics stream is `workspace.broadcast` or a canonical module's output stream; `cycle.out` is present; `cycle.tick` is not.

## 2. Bus decode
- [ ] 2.1 The read-path decoder turns a workspace entry into a `workspace.broadcast` event (source, type, payload, timestamp, salience as specified); corrupt snapshots are skipped.
- [ ] 2.2 Tests on fakeredis: an entry written by the real `publish_workspace` is read back as that event; a corrupt snapshot is skipped; `subscribe_workspace` is unchanged.
- [ ] 2.3 Test: the Nexus bridge relays a published broadcast and a `cycle.tick` to a client, after the privacy filter.

## 3. Charts
- [ ] 3.1 Chart routing is a pure function on the page; coherence from broadcasts, salience chart without `cycle`/`syneidesis` events.
- [ ] 3.2 Real-browser test of the routing function (system Chrome via Playwright, as the layout test does).

## 4. Docs
- [ ] 4.1 Nexus chapter: the chart sources, if described.
