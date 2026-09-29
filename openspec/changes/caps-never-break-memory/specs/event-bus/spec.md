## MODIFIED Requirements

### Requirement: Stream retention via MAXLEN
Every `publish` call SHALL trim the target stream to the configured maximum length using Redis Streams' approximate trimming (`XADD ... MAXLEN ~ N`). The default maximum SHALL be 100000 entries per stream and SHALL be overridable in `config/kaine.toml` either globally or per stream. The shipped configuration SHALL keep enough lookback on the high-rate streams that an observer or archive restart of several minutes loses no records: `topos.out` and `audition.out` SHALL be 12000 entries (about 20 minutes at 10 Hz; a `topos.out` entry is about 40 KB) and `workspace.broadcast` SHALL be 100000 entries. The memory these caps imply is checked before boot by the pre-boot bus budget row. The bus config loader SHALL merge an operator overlay TOML (`kaine.operator.toml`) into the base config so per-stream maxlen overrides are honored.

#### Scenario: Stream stays under configured cap
- **WHEN** 200000 events are published in succession to a stream with `maxlen = 100000`
- **THEN** the stream length reported by `XLEN` after the publishes is within 10% of 100000

#### Scenario: Latent-vector streams are capped lower by default
- **WHEN** the committed `config/kaine.toml` is inspected
- **THEN** `[bus.per_stream_maxlen]` contains `"topos.out" = 12000`, `"audition.out" = 12000` and `"workspace.broadcast" = 100000`
- **AND** `[bus].default_maxlen` is 100000

#### Scenario: Operator overlay overrides per-stream maxlen
- **WHEN** `kaine.operator.toml` sets `"topos.out" = 500` and `load_bus_config()` is called
- **THEN** the resulting `BusConfig.per_stream_maxlen["topos.out"]` is 500

#### Scenario: Operator overlay does not affect unrelated keys
- **WHEN** `kaine.operator.toml` only changes per-stream maxlen
- **THEN** `BusConfig.default_maxlen` and other settings remain at their base-config values

## ADDED Requirements

### Requirement: Typical event sizes for bus budgeting
`kaine/bus/config.py` SHALL provide a table of typical serialized event sizes per stream, used only to estimate bus memory before boot. The table SHALL hold the measured values `topos.out` 40 KB, `workspace.broadcast` 6.6 KB, `chronos.out` 1.3 KB, `soma.out` 0.55 KB, `cycle.out` 0.25 KB and `audition.out` 0.4 KB, and every other stream SHALL use a 2 KB default. The table SHALL be documented as estimates, not limits.

#### Scenario: A measured stream uses its measured size
- **WHEN** the typical size of `topos.out` is looked up
- **THEN** it is 40 KB

#### Scenario: An unmeasured stream uses the default
- **WHEN** the typical size of `mnemos.out` is looked up
- **THEN** it is 2 KB
