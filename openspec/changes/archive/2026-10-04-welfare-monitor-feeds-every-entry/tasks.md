## 1. Monitor
- [x] 1.1 `_poll_once` feeds every soma report, advances to the last scanned id, collects crossings, drains gray-zone events every poll, and responds in order until the monitor has acted.
- [x] 1.2 `_drain_gray_zone` feeds every event and returns every crossing.

## 2. Tests
- [x] 2.1 One poll consumes the whole batch: every report and event reaches the trackers and the cursors reach the end.
- [x] 2.2 Pause acts once when one poll holds several crossings, with a stubbed and with the real response (one preservation bundle, one freeze); notify responds to each crossing, and with the real response the rate limit lets one bundle through; the gray-zone drain runs even after a distress crossing. Removing the `_acted` latch fails the pause tests; restoring stop-at-crossing or skipping the drain fails theirs.

## 3. Specs
- [x] 3.1 The event-bus delta of `cursors-advance-past-undecodable` no longer describes the welfare monitor stopping at a crossing.
