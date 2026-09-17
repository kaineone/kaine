## MODIFIED Requirements

### Requirement: Stream retention via MAXLEN
Every `publish` call SHALL trim the target stream to the configured maximum length using Redis Streams' approximate trimming (`XADD ... MAXLEN ~ N`). The default maximum SHALL be 100000 entries per stream and SHALL be overridable in `config/kaine.toml` either globally or per stream. The shipped configuration SHALL cap latent-vector streams (`topos.out`, `audition.out`) to a lower bound because each entry is approximately 40 KB. The bus config loader SHALL merge an operator overlay TOML (`kaine.operator.toml`) into the base config so per-stream maxlen overrides are honored.

#### Scenario: Stream stays under configured cap
- **WHEN** 200000 events are published in succession to a stream with `maxlen = 100000`
- **THEN** the stream length reported by `XLEN` after the publishes is within 10% of 100000

#### Scenario: Latent-vector streams are capped lower by default
- **WHEN** the committed `config/kaine.toml` is inspected
- **THEN** `[bus.per_stream_maxlen]` contains `"topos.out" = 2000` and `"audition.out" = 2000`

#### Scenario: Operator overlay overrides per-stream maxlen
- **WHEN** `kaine.operator.toml` sets `"topos.out" = 500` and `load_bus_config()` is called
- **THEN** the resulting `BusConfig.per_stream_maxlen["topos.out"]` is 500

#### Scenario: Operator overlay does not affect unrelated keys
- **WHEN** `kaine.operator.toml` only changes per-stream maxlen
- **THEN** `BusConfig.default_maxlen` and other settings remain at their base-config values
