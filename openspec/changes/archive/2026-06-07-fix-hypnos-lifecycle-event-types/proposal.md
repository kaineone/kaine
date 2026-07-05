## Why

The `hypnos` spec (§"Hypnos publishes lifecycle events") mandates Hypnos publish
`hypnos.sleep.started` and `hypnos.sleep.completed` on `hypnos.out`, and the
producer + Hypnos's own tests honor that. But **three consumers filter for event
types Hypnos never emits** (re-audit finding, same class as the Lingua
speech-type bug):
- `kaine/evaluation/sleep_snapshots.py` filters `hypnos.began_rest` /
  `hypnos.ended_rest` → sleep snapshots are never recorded.
- `kaine/nexus/conversation.py` filters `hypnos.began_rest` /
  `hypnos.ended_rest` → the conversation sleep-state badge never updates.
- `kaine/evaluation/voice_tracking.py` filters `hypnos.cycle_complete` → voice
  alignment metrics are never logged.

All three are silently dead whenever Hypnos runs. Their tests pass only because
they hand-build events with the wrong (consumer-side) types — no test exercises
the real Hypnos producer against these consumers.

## What Changes

- Align the three consumers to the canonical Hypnos lifecycle types:
  `began_rest` → `hypnos.sleep.started`, `ended_rest`/`cycle_complete` →
  `hypnos.sleep.completed`.
- Correct the consumer tests that encoded the wrong types (they become the
  regression guard), and add coverage that the conversation sleep badge reacts
  to the canonical events.

## Capabilities

### Modified Capabilities

- `hypnos`: make explicit that consumers of the sleep lifecycle events filter on
  the canonical published types (`hypnos.sleep.started` / `.completed`), so the
  evaluation observers and the conversation sleep-state badge actually receive
  them.

## Impact

- **Code**: `kaine/evaluation/sleep_snapshots.py`, `kaine/evaluation/
  voice_tracking.py`, `kaine/nexus/conversation.py` (event-type strings only;
  no producer change — Hypnos is correct per spec).
- **Tests**: correct the wrong-type literals in `tests/test_evaluation_observers.py`;
  add a conversation sleep-state assertion. No skips/weakening.
- **Behavior**: when Hypnos runs, sleep snapshots + voice-alignment metrics are
  recorded and the conversation sleep badge toggles, as designed.
