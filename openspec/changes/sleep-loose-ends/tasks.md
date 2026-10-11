## 1. Implementation

- [x] 1.1 Phantasia gains an explicit scenario window; Hypnos opens it before phase 2 and closes it in a `finally` after phase 3; `hypnos.sleep.started` no longer opens it
- [x] 1.2 Phantasia answers a replay cue whose timestamp lies inside the latest window even when the poll handles it after the window closed
- [x] 1.3 Hypnos `shutdown()` cancels and awaits an in-flight sleep, then awaits its held shielded tasks, each wait bounded
- [x] 1.4 A non-finite payload timestamp ranks as 0.0 in `recent_points` on every backend
- [x] 1.5 Tests: the window through a real sleep on the bus, the window closing on a cancel, shutdown during a sleep and during a held reset, non-finite timestamps on the in-memory, sqlite-vec and Qdrant backends
- [x] 1.6 Docs: Phantasia, Hypnos and sleep pages
