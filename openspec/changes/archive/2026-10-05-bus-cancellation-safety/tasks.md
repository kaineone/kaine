## 1. Implementation

- [x] 1.1 Add the cancellation-aware client adapter to `kaine/bus/client.py`. It
      wraps calls that return a coroutine (every redis-py command) in a guard that raises
      `CancelledError` when `Task.cancelling()` rose during the call. It passes
      through non-callable attributes, non-awaitable results, and attribute
      assignment and deletion.
- [x] 1.2 `AsyncBus.__init__` wraps the injected or constructed client in it.
- [x] 1.3 Remove the per-generator pending-cancel check (the adapter covers it).

## 2. Tests

- [x] 2.1 Each workspace subscription ends as cancelled within 2 s when the
      client swallows the cancellation.
- [x] 2.2 A `BaseModule` whose client swallows the cancellation completes
      `shutdown()` within 2 s.
- [x] 2.3 A plain bus call (`publish`) whose client swallows a cancellation
      raises `CancelledError`.
- [x] 2.4 Cleanup after a caught cancellation: bus calls made inside
      `except CancelledError:` complete and return their results.
- [x] 2.5 Pass-through: `bus.client` attribute reads and assignments reach the
      underlying client, and a non-awaitable result is returned unchanged.
- [x] 2.6 Normal delivery is unchanged (control tests with a real fakeredis
      client).
- [x] 2.7 Mutation check: with the guard disabled, 2.1 to 2.3 fail within
      seconds, never hanging the suite.
- [x] 2.8 The full suite passes on Python 3.11 and 3.12, including
      `tests/systems/test_eidolon_subsystem.py` and
      `tests/test_hypnos_rest_requests.py` on 3.11. CI runs the suite on both versions on every PR and nightly; green on main (verified 2026-10-05).
