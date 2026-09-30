# Bus calls re-raise a cancellation the Redis client swallowed

## Why

KAINE stops its long-running loops by cancelling their tasks. These include
every module's workspace subscription, Lingua's snapshot cache, Hypnos's
volition consumer, the evaluation sidecars and the Nexus bridge. A loop ends
only if the `CancelledError` reaches it.

On Python 3.11, `asyncio.wait_for` drops a cancellation that arrives just as the
awaited operation completes. It returns the result, and the task stays marked as
cancelling but keeps running. Python 3.12 rewrote `wait_for` on `asyncio.timeout`,
which fixes this. redis-py 8 gives each connection a 5-second `socket_timeout` by
default. So it sends every command, including the connect-time health check,
through `asyncio.wait_for(..., socket_timeout)`. redis-py 5 left the timeout unset
and wrote to the socket directly.

So with redis-py 8 on Python 3.11, any bus call can swallow the cancel meant to
stop the loop around it. The loop keeps running, and the `shutdown()` that awaits
it never returns. This showed up as hangs in the Python 3.11 CI job, in module
teardown (`tests/systems/test_eidolon_subsystem.py`) and in Hypnos's consumer
loop (`tests/test_hypnos_rest_requests.py`). Both pass with redis-py 5 and hang
with redis-py 8. The same `wait_for` is on the real connection's send path, so
this is not limited to the test double. Python 3.11 is a supported floor
(`requires-python >= 3.11`).

## What Changes

- `AsyncBus` wraps its Redis client, the injected one or the one it builds, in a
  thin cancellation-aware adapter. Every client call that returns a coroutine
  is awaited through a guard. If the calling task's cancellation count
  (`Task.cancelling()`, Python 3.11+) rose during the call, and the call still
  returned normally, the guard raises `CancelledError`. The cancellation then
  reaches the loop that owns the task.
- The guard compares the count before and after the call. It does not test for a
  non-zero count, so cleanup that runs after a task caught its own
  cancellation is unaffected: a shutdown path flushing state over the bus is an
  example. A library that handles its own timeout cancellation and calls
  `uncancel()` (as `asyncio.timeout` does) is also unaffected.
- `AsyncBus.client` returns the adapter. So code that reaches the raw client
  directly gets the same guarantee: the Nexus bridge and Perception both do.
  Attribute reads and assignments pass through to the underlying client.
  Non-awaitable results, such as `pipeline()`, are returned unchanged.
- There is no behaviour change when cancellation is delivered normally.

## Impact

- `kaine/bus/client.py`: the adapter, used in `AsyncBus.__init__`.
- Tests: `tests/test_bus_subscriber_cancellation.py` (the workspace
  subscriptions, module shutdown, a generic bus call, the cleanup-after-cancel
  case, and attribute pass-through).
- Every in-process Redis loop goes through `AsyncBus`. Pre-boot and the Nexus
  health probe make one-shot calls. The study runner uses the synchronous
  client.
