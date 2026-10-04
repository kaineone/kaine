## 1. Boot
- [x] 1.1 A phase that raises triggers `_release_after_failed_boot` (cancel boot tasks, stop the welfare producer, close the bus; modules are not shut down), then re-raises.
- [x] 1.2 Revive refusal: modules shut down in `_revive_or_refuse`; the caller stops the welfare producer, then closes the bus.
- [x] 1.3 Remove `MetricsCollector`.
- [x] 1.4 Vox's backend registry defaults to `"chatterbox"`.

## 2. Config
- [x] 2.1 `validate_config_shape` checks `[empatheia].operator_sources` is a list of strings.

## 3. Tests
- [x] 3.1 A failing phase releases the bus, the producer and a started task, re-raises, and shuts no module down; removing the release fails the test.
- [x] 3.2 The revive refusal shuts the modules down and takes no bus; the config check; no MetricsCollector; the Vox default.
