## 1. Shadow forward models

- [x] 1.1 `widened_copy` and `hindsight_step` on the Topos, Audition and Soma forward models
- [x] 1.2 Tests: the copy predicts like the original, leaves the global RNG alone, and hindsight equals the live step

## 2. Controller

- [x] 2.1 `kaine/modules/positive_control.py`: settings, component sources, shadow probes, per-processor controller, result publishing
- [x] 2.2 Tests: settings validation, component moments, detection of an informative component and no detection of a non-informative one, no verdict without a minimum effect, live model untouched, sleep not counted

## 3. Wiring and records

- [x] 3.1 Topos, Audition and Soma build and step the control only when `[positive_control]` enables it; factories and `construct_module` pass the section
- [x] 3.2 `positive_control.out` in the stream registry; research-log taxonomy; range sweep
- [x] 3.3 `python -m kaine.experiment.positive_control <run_id>` all-processors verdict; no study gate exists, so it is recorded and checked offline
- [x] 3.4 `config/kaine.toml` ships the section disabled with `min_effect` and `snr` unset
- [x] 3.5 Docs: configuration appendix, research event streams, module pages, researcher and experiment chapters

## 4. Before the live runs (operator)

- [ ] 4.1 Fix `min_effect` and `snr` with the preregistration and run the control on the live tier until every processor passes
