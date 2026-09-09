## Why

A correctness review (every finding verified against code with file:line) identified four critical, four high, three medium, and four low bugs that would corrupt or ruin a multi-day unsupervised research run. Three classes of failure:

1. **Welfare/safety semantics are load-bearing and broken.** Freezing permanently blinds the entity (C1), Spot recovery can silently lift a welfare-protective pause and never re-fire the welfare latch (C2), and one failed LLM call permanently mutes the entity because no guard-clearing event is ever published (C3).
2. **Streams stall or replay silently.** A single poison batch permanently stalls hot consumers (H2), an in-run engine restart replays stale events up to `maxlen` — including soma rate advisories that drive activity to the floor (H3) — and playlist audio desynchronizes from the shared clock on any producer restart (H1). The report-policy novelty guard never expires, driving external speech to zero over days (H4) — thesis-fatal.
3. **Silent maintenance decay.** The interval-sleep safety-net is dead code (M1), a transient publish failure during sleep leaves Soma applying faster decay forever (M2), unrate-limited welfare notify fires ~5,700 encrypted bundles over 48 h toward disk exhaustion (M3), plus cheap engine hygiene (L1–L4).

Unfixed, these bugs are not UX annoyances: they cause permanent blindness, permanent muteness, welfare-pause violation, indefinite stalls, and disk exhaustion in the preservation system itself — precisely the failure modes a multi-day run cannot survive.

## What Changes

All changes are plumbing and safety; none author entity behavior (emergent-not-hardwired does not apply). Zero raw-sense-data persistence is unchanged. Safety over UX throughout.

**Phase 1 — Freeze/welfare safety (C1, C2, M3).**
- C1 (`kaine/cycle/__main__.py:377-390`): snapshot desired audio/video flags at freeze; restore them on resume.
- C2 (`kaine/cycle/control_state.py:76-87`, `spot.py:537-539`, `preservation_monitor.py:874-877`): freeze sources stack with priority. **Guarantee: a welfare pause can only be lifted by the operator or an explicit welfare stand-down — never by Spot recovery.** Spot, on recovery, restores the exact pre-existing freeze state (reason, source, stack) rather than unconditionally unfreezing. The monitor's `_acted` latch (:704,:894) is consulted so a latched welfare action is never re-liftable.
- M3 (`preservation_monitor.py:894`): apply the same `min_interval_s` rate limit DivergenceMonitor already has to the "notify" response.

**Phase 2 — Speech liveness (C3, H4).**
- C3 (`lingua/module.py:375-387`, `volition.py:209-217`, `report_policy.py:128-138`, `drive_policy.py:89-103`): on generation failure, publish a **content-free** realization-failed event (mode + reason class only, never text, no payloads). All three policies treat it as clearing speak/think in-flight guards; add a refractory-scaled timeout on the guards as belt-and-suspenders.
- H4 (`report_policy.py:106,176,194-198`): time-based signature expiry (`sig_expiry_s`, configurable, using the policy's clock).

**Phase 3 — Feeds and cursors (H1, H2, H3).**
- H1 (`audition/feed.py:432-499`): on producer start, call `PlaylistClock.locate()` and seek/skip forward to the clock position (seek within the current item to the offset; otherwise skip decoded frames).
- H2 (`engine.py:410,775-783,630-631,670-671`; `soma/module.py:517-518`; `hypnos/module.py:228-229`): switch from `read()` + last-decoded to `read_entries`/`last_scanned`, as the preservation monitor and the bus's own warning (`bus/client.py:192-201`) prescribe.
- H3 (`engine.py:164,167,186`): seed all stream cursors to the stream tail at startup (precedent: `hypnos/module.py:186-195`).

**Phase 4 — Sleep robustness (M1, M2, L3).**
- M1: a periodic `RestScheduler.is_due()` poll task inside Hypnos, subjective-clock paced, fulfilling the `boot.py:1248-1249` promise.
- M2 (`hypnos/module.py:340..432`): try/finally around `hypnos.sleep.completed` so Soma (`soma/module.py:550-565`) never believes the entity is asleep after a transient failure (finally-publish, or a sleep-failed event handled identically).
- L3 (`hypnos/module.py:253-256,267-277,424`): hold a reference to the sleep task (GC hazard); guard the trigger flag against double-trigger mis-annotation.

**Phase 5 — Engine hygiene (L1, L2, L4).**
- L1 (`engine.py:226-230`): accumulate deterministic logical time incrementally instead of recomputing past ticks' period.
- L2 (`engine.py:785-791`): clamp the experiential accumulator when throttled below the experiential rate.
- L4 (`engine.py:626-627,666-667`): log bare except-returns at WARNING with rate limiting.

**Phases 6–7:** every fix gets a regression test keyed to its exact failure scenario (test names below); docs updated in present tense.

## Impact

- **Files:** `kaine/cycle/__main__.py`, `control_state.py`, `spot.py`, `preservation_monitor.py`, `engine.py`, `kaine/modules/lingua/module.py`, `kaine/workspace/volition.py`, `report_policy.py`, `drive_policy.py`, `kaine/modules/audition/feed.py`, `kaine/modules/soma/module.py`, `kaine/modules/hypnos/module.py`, `kaine/bus/` (if helpers needed), tests, docs.
- **Behavioral guarantees added:** freeze never blinds (C1); welfare pauses are operator/welfare-liftable only (C2); the entity can always speak again after a failed realization (C3); audio/video stay clock-synced across producer restarts (H1); no stream stalls on poison (H2); no stale-event replay on restart (H3); report suppression expires (H4); maintenance runs even without fatigue (M1); sleep state cannot wedge (M2, L3); notify is rate-limited (M3).
- **No new persistence**; zero raw-sense-data persistence unchanged. No entity behavior is authored. Rollout risk is low and confined to safety plumbing; C2's stack/priority semantics are the most load-bearing and get the most tests.
- **Docs:** update freeze/welfare semantics, consumer-cursor guidance, realization-failure semantics, and boot promise notes in present tense.

