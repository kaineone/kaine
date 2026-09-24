## 1. Implementation

- [x] 1.1 Spot heavy restart: read the predecessor's oscillator before shutdown and attach it to the rebuilt module before it is initialized and registered.
- [x] 1.2 `rewire_module` no longer calls `_wire_oscillators`; boot wiring is unchanged.
- [x] 1.3 `docs/plugins.md`: `make_oscillator` is called once per declared seam at boot; restarts keep the oscillator.

## 2. Tests

- [x] 2.1 A heavy restart gives the rebuilt module the same oscillator object (default and plugin) with its phase history.
- [x] 2.2 Healthy modules' oscillators are the same objects after another module's heavy restart.
- [x] 2.3 A plugin's `make_oscillator` is called once at boot and not again across two heavy restarts, and no oscillator-less window occurs.
- [x] 2.4 With the oscillator layer disabled, restarts attach no oscillator.
