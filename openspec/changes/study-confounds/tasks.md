## 1. Implementation

- [x] 1.1 Per-feed `source_label` on the live-microphone path.
- [x] 1.2 Empatheia attribution by channel and `[empatheia].operator_sources`.
- [x] 1.3 Volition treats only operator-channel transcriptions as addressed speech.
- [x] 1.4 `Vox.set_dormant`; dormant during gestation, activated at birth.
- [x] 1.5 `docs/operations.md` and `config/kaine.toml` comments.

## 2. Verification

- [x] 2.1 Tests: each feed mode sets its label and a real device keeps `live_mic`; Empatheia attributes operator channels to the speaker label, other channels to `media:<channel>`, and a missing label to the speaker label; Volition answers operator-channel speech and not playlist speech, and still answers events without a label; dormant Vox renders nothing and resumes after activation; a gestating boot holds Vox and birth activates it.
- [x] 2.2 Offline suite green; `openspec validate study-confounds --strict`.
