# Boot follow-ups: a failed boot releases what it holds

## Why

Mapping `_boot_and_run` for the boot-phases change (W5) found five problems that change recorded and left for later:
- **A failed boot leaked its resources.** Cleanup ran only once the run loop started. A phase that raised after the bus opened left the bus, the welfare producer and any started tasks running.
- **Inconsistent shutdown order on early exits.** The revive-refusal exit closed the bus before stopping the welfare producer, which reads the bus. The womb-hold exit stops the producer first.
- **A late config check.** `[empatheia].operator_sources` was checked only after every module had been built.
- **A pretend process.** `MetricsCollector` was constructed and thrown away, under a comment saying it made metrics reachable by Nexus. Nothing read it; Nexus gets its metrics from the runtime state file.
- **A misleading default.** `make_vox` built its backend registry with `default="sherpa_onnx"` while the real default, from the factory and the shipped config, is `"chatterbox"`.

## What changes

- **A failed boot releases what it holds.** When a phase raises, the runner calls `_release_after_failed_boot` and re-raises. It:
  - cancels every boot task already started;
  - stops the welfare producer;
  - closes the bus.

  It deliberately does not shut the modules down. A module's shutdown persists its state, Phantasia's world-model weights for example, and a half-built boot must not write that state over a good saved copy.
- **Anything that uses the bus stops before the bus closes.** `_revive_or_refuse` only shuts the modules down. Its caller then stops the welfare producer and closes the bus.
- **`[empatheia].operator_sources` is checked when the config loads**, by `validate_config_shape`.
- **`MetricsCollector` is removed.**
- **Vox's registry default is `"chatterbox"`.**

## Not changed

`MaturationConfig` is built three times from the same table, and `[cycle]` and the organ model id are each read twice. That is harmless duplication; leaving it avoids moving state between phases.

## Impact

- **Behaviour:** only on failure paths. A failed boot now releases its bus, welfare producer and tasks before the process exits. A revive refusal stops the welfare producer before closing the bus. A malformed `operator_sources` is refused when the config loads.
- **Research:** none. No study is running.
