# Tasks

## 1. Injectable event timestamps
- [x] 1.1 Add `wall_clock: Callable[[], datetime]` to `CognitiveCycle.__init__` (default real `datetime.now(timezone.utc)`); keep the existing monotonic `clock` for durations.
- [x] 1.2 Route the three `datetime.now(timezone.utc)` sites (`engine.py:264, 317, 533`) through a single `self._now()`.
- [x] 1.3 Add `deterministic: bool = False`; `self._now()` returns a logical timestamp (`BASE_EPOCH + tick_index * target_tick_period`) when deterministic, else `self._wall_clock()`.

## 2. Canonical within-tick event ordering
- [x] 2.1 Before scoring/selection, order the per-tick event list by `(source, type, entry_id)`. Applied unconditionally (existing tests stay green); decision documented in design.md.

## 3. Wiring + config
- [x] 3.1 `kaine/cycle/__main__.py`: read `[experiment].deterministic`; construct the engine with `deterministic=` set. (Seed already set by experiment-run-identity.)
- [x] 3.2 `config/kaine.toml`: add `deterministic = false` under `[experiment]` with a comment.

## 4. Determinism test harness + tests
- [x] 4.1 A scripted-input harness driving the engine N ticks deterministically with a fixed seed (reused by the test).
- [x] 4.2 Twice-run identity test: identical selected entries + salience + inhibited + volition decisions + logical timestamps across runs; exclude `wall_duration_ms`/`slip_ms`.
- [x] 4.3 Logical-clock test (timestamps = BASE_EPOCH + tick*period, identical across runs); injected-wall-clock test in normal mode.
- [x] 4.4 Canonical-ordering test (scrambled arrival → stable selection tie-break).
- [x] 4.5 Default-off: existing engine/cycle tests green with `deterministic=false`.

## 5. Docs + validation
- [x] 5.1 Docs: present-tense section on deterministic mode + what is/isn't guaranteed (trajectory yes, wall-clock latency no).
- [x] 5.2 Targeted suite green; `openspec validate deterministic-cycle-mode --strict`. (PM runs the full suite.)
