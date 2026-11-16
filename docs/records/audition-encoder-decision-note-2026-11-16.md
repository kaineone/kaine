# Audition encoder decision note — 2026-11-16

Source record: `docs/records/audition-encoder-bakeoff.json`
Config: 600 blocks × 8000 samples @ 16 kHz, surprise every 150 blocks, seed 42, device cuda:0.

## Result on the currently evaluated feed

Single deterministic synthetic feed only (pink-ish noise with a 1 kHz
surprise chirp every 150 blocks). All three encoders tie on false-alert
rate; separation and cost differ:

| encoder | ROC AUC | false alerts/min | p95 latency (ms) | peak RSS (MB) | embed dim |
|---|---:|---:|---:|---:|---:|
| spectral | 0.9992 | 6.0 | 1.62 | 285 | 64 |
| wavjepa | 0.9950 | 6.0 | 6.55 | 3142 | 768 |
| dasheng | 0.9836 | 6.0 | 3.79 | 1713 | 768 |

Ranking by the 6.6 criteria:
1. ROC AUC (higher better): spectral > wavjepa > dasheng.
2. False alerts/min (lower better): three-way tie at 6.0.
3. p95 latency (lower better): spectral < dasheng < wavjepa.

Cost confounders not in the three 6.6 criteria but in the same record:
- Peak RSS favours spectral by 6–11× over the SSL encoders.
- Embedding dimension 64 vs 768 affects forward-model and persistence cost.

## Complete (evidence in hand)

- Bake-off harness exists at `scripts/bench_audition_encoders.py` and runs
  offline without booting an entity.
- Encoders dasheng and wavjepa vendored/registered with ONNX + int8 exports
  and parity tests (tasks 6.1–6.4 already ticked).
- Energy channel (6.5) available.
- Deterministic seeded synthetic feed evaluated; JSON record written under
  `docs/records/`.
- Provisional ordering on that feed: spectral leads on AUC and latency, tie
  on false alerts.

## Not yet complete / still open

- 6.6 is **not complete**: only one of the three required feed families
  (seeded, playlist, stimulus source) has been run. The playlist and stimulus
  source feeds still need to be replayed through the harness with their event
  marks before any winner can be declared.
- 6.7 is **not started**: acoustic salience recalibration (normalisation,
  alert factor, floor) for the winner on all three feeds.
- 6.8: winner promotion to `first_configuration` profile default still pending;
  Tier 0 stays `spectral`. Notice/licence entries still pending.
- 6.9: WavJEPA mismatch (MMN) mode results not yet in the record.
- 6.10: paper revision note still pending.

No task checkboxes were changed by this note. 6.6 and 6.7 remain open until
the two additional feed families are evaluated and recalibration lands.
EOF
## 1200-block snapshot (2026-11-16, stdout redirect)

Source record: `docs/records/audition-encoder-bakeoff-1200blocks.json`
Config: 1200 blocks × 8000 samples @ 16 kHz, surprise every 150 blocks, seed 42, device cuda:0.

| encoder | ROC AUC | false alerts/min | p95 latency (ms) |
|---|---:|---:|---:|
| spectral | 0.989 | 6.00 | 3.09 |
| wavjepa | 0.997 | 6.00 | 6.24 |
| dasheng | 0.927 | 6.00 | 3.86 |

Spectral does **not** still lead ROC AUC on this snapshot: WavJEPA (0.997)
exceeds spectral (0.989), with dasheng (0.927) behind both. False alerts/min is
a three-way tie at 6.00 as before. Spectral still leads p95 latency (3.09 ms
vs dasheng 3.86 ms and wavjepa 6.24 ms). Conclusion per p95/FA: spectral
retains latency leadership and the FA tie, but not AUC leadership; result
remains single-feed (seeded synthetic) and does not settle 6.6.
