## 1. Implementation

- [x] 1.1 `analysis.py`: reading (plain and encrypted), programme time, per-viewing measures, per-step comparisons, the limits text, JSON and Markdown output.
- [x] 1.2 The `analyse` subcommand.
- [x] 1.3 `docs/operations.md`: reading the study's report.

## 2. Verification

- [x] 2.1 Tests on synthetic ignition logs: rates exclude paused time; film-minute bins and absent bins; coalition sizes and module shares; drift; `seq` gaps as drops; encrypted lines decrypt, and unreadable lines are counted; main − control and step deltas; correlation needs 30 shared bins; the report contains no payload keys and includes the limits.
- [ ] 2.2 Offline suite green; `openspec validate ignition-analysis --strict`.
