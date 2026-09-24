# Substrate foundation: implementation results & findings

The `cl1-substrate` foundation
([`wetware-substrate-foundation`](../openspec/changes/wetware-substrate-foundation/))
is implemented and verified end-to-end against the vendored simulator. This
records how to reproduce it and what the simulator does, including three
non-obvious behaviours the design had to accommodate.

## Reproduce

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ./vendor/cl-sdk        # the simulator (numpy-light)
pip install -e . --no-deps            # kaine_cl1 (the heavy `kaine` dep is not
                                      # needed for the substrate layer)
pip install pytest
python -m pytest tests/ -q            # 24 passing: pure logic + live-sim closed loop
```

`tests/test_foundation_pure.py` covers allocation, routing, cadence math, encoder
safety, and decoders with no simulator. `tests/test_foundation_sim.py` opens the
real simulator and exercises the closed loop: determinism, territory isolation,
stim→evoked response, cadence aggregation, and live surprise decoding.

## What's implemented

| Piece | Module | Verified by |
|---|---|---|
| Owned session, env, simulator guard, deterministic frame read | `substrate/session.py` | session smoke, determinism tests |
| Deterministic, **stim-responsive** reference culture | `substrate/sources.py` | `test_reference_source_is_deterministic` |
| Channel allocation + oversubscription ceiling | `substrate/broker.py` | `test_oversubscription_fails_at_allocation` |
| Single closed loop, spike routing, cadence nesting | `substrate/broker.py` | `test_broker_*`, `test_cognitive_tick_*` |
| Rate/population encoders (SDK-limit-safe), firing-rate + LZ surprise decoders | `substrate/codec.py` | `test_encoder_*`, `test_surprise_*` |

## Three findings that shaped the design

### 1. The default random source is not reproducible in-process; the closed loop can't respond to stim
Cortical Labs documents that the free simulator "generates non-learning control
data that does not respond to stimulation." Confirmed: stimulation leaves the
default data stream unchanged, and re-opening the device in one process continues
the frame clock rather than resetting it, so two in-process runs read different
timeline regions. **Response:** a pluggable `ReferenceCulture` data source
(`cl.sim.set_simulator_data_source`) that is (a) a pure function of absolute
timestamp (reproducible in-process and across processes) and (b) stim-responsive,
so encode→stim→record→decode is a real loop for offline characterisation. Not a
biophysical model; the real culture replaces it entirely.

### 2. `loop()` tick segmentation is nondeterministic under accelerated time
The number of frames per loop tick varies run-to-run, so *counting sub-ticks*
gives a non-reproducible spike partition. **Response:** the broker aggregates by an
exact **timestamp span** (`nesting_factor × frames_per_sub-tick`) with a spillover
buffer for spikes past the boundary. Given a deterministic source, the per-tick
spike set is then a pure function of the timeline. This is why reproducible
evaluation uses the frame-count/`read()` clock, not wall-clock tick boundaries.

### 3. The simulator silently swallows stimulation on channel 0
`ChannelSet(0)` stims never commit (no stim record, no evoked response), while
channels 1..63 work: a 0-is-falsy quirk in the SDK stim path. **Response:** the
broker reserves channel 0 out of every territory (`reserved_channels={0}`), so no
module can depend on it. Pinned as a regression in
`test_channel_zero_is_unstimulable`.

## Live integration against real KAINE

The Chronos reference conversion is verified against the **actual** pinned `kaine`
module (not a stand-in): stock `Chronos(bus, network=WetwareTimingModel(...))` over
a `fakeredis` bus publishes the same `chronos.out` contract as a silicon network
(`tests/test_chronos_integration.py`). The seam confirmed: `Chronos.__init__`
takes `network=` and builds its silicon CfC only when that is `None`, so the
conversion is pure injection, with no upstream edit.

To run the integration tests you need the `kaine` stack importable alongside the
simulator. On the build machine that is one editable install into this venv:

```bash
. .venv/bin/activate
pip install -e /path/to/kaine --no-deps   # kaine's heavy deps are already present
pip install redis fakeredis               # light: bus client + in-memory bus
python -m pytest tests/ -q                # 29 passing (sim-only + live kaine)
```

The integration tests `pytest.importorskip("kaine")`, so on a machine without the
stack the suite still runs (sim-only) and skips them. The forward-prediction
head (`temporal_prediction_error`) uses torch; its predictive behaviour is covered
at the model level by `test_chronos_wetware.py`, and the live test covers the event
contract and the module running end-to-end on the substrate.

## Deferred (honestly)

- **Downstream boot** (`build_wetware_registry`) that constructs real KAINE
  modules and injects CL1 backends needs the pinned `kaine` dependency installed;
  it begins with the Chronos conversion.
- **Background-thread real-time drive** and a starvation probe are only meaningful
  on hardware (accelerated time covers offline/sim runs); they land with the
  hardware phase.
- **Temporal encoder** and a **functional-connectivity decoder** land with the
  first module that needs each (Chronos; Empatheia/Nous).
