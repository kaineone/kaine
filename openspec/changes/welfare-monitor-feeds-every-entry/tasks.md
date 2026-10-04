## 1. Monitor
- [x] 1.1 `_poll_once` feeds every soma report, advances to the last scanned id, collects crossings, drains gray-zone events every poll, and responds in order until the monitor has acted.
- [x] 1.2 `_drain_gray_zone` feeds every event and returns every crossing.

## 2. Tests
- [x] 2.1 One poll consumes the whole batch: every report and event reaches the trackers and the cursors reach the end.
- [x] 2.2 Pause acts once when one poll holds several crossings; notify responds to each; the gray-zone drain runs even after a distress crossing. Each guard fails when its fix is reverted.

## 3. Specs
- [x] 3.1 The event-bus delta of `cursors-advance-past-undecodable` no longer describes the welfare monitor stopping at a crossing.
