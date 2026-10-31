## 1. Code (one pull request)

- [ ] 1.1 `reference` on `EmbodimentCapabilities`; the stub sets it. Test: extend `tests/test_embodiment_module.py`.
- [ ] 1.2 The factory refuses a reference adapter and `"none"` with a boot refusal; shipped `[embodiment].adapter = "none"`; tests that relied on the factory building the stub move to direct construction. Tests: `tests/test_embodiment_reference_body.py` (boot refusal, shipped value).
- [ ] 1.3 `probe_available()` false for a reference adapter; `forwarded` true only from a non-reference adapter. Tests: extend `tests/test_embodiment_module.py` and add a maturation-gate case to the gate runner tests (a reference body never makes the stage `embodied`).
- [ ] 1.4 Config validation refuses an enabled control surface without a registered motor-seam driver. Test: extend `tests/test_embodiment_control_surface.py`.
- [ ] 1.5 `embodiment_built()`; the wizard module step, `kaine/dashboard/health/blocks.py` and `kaine/research/ignition_study/__main__.py` read it. Tests: wizard step without the toggle; study `init --order embodiment` refused; dashboard block shows held.
- [ ] 1.6 Docs: `docs/09-modules/embodiment.md` status ("held: control plane and curriculum built and unit-tested; no body adapter and no motor loop are built"), `docs/20-embodiment-adapters.md`, `docs/15-experiments/ignition-study.md`, the `[embodiment]` comments in `config/kaine.toml`. A docs check fails if the module page claims a built body while `embodiment_built()` is false.
- [ ] 1.7 `openspec validate embodiment-held-status --strict`.

## 2. Hand-over

- [ ] 2.1 Add to `embodiment-motor-contingency` tasks 2.1 and 2.4 a line that registering the driving loop and the pan-tilt adapter makes `embodiment_built()` true, and that those tasks update the docs check's expectation.
