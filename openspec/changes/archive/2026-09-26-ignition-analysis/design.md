# Design — `ignition-analysis`

## Reading

- For each `steps.jsonl` record with `outcome == "complete"` and a viewing step, read every `*.jsonl` file in `ignition_log_dir` whose records carry that step's `run_id`. The sink stamps `run_id` and `seq` on every record.
- **Decryption.**
  1. If a line does not parse as JSON, install the state encryptor (`install_from_section({"enabled": True})`, with the key from `KAINE_STATE_KEY` or the keyring) and decrypt it with `get_state_encryptor().decrypt_text`.
  2. A line that fails both is counted as unreadable and reported, never guessed.
- Records are ordered by `seq`. Gaps in `seq` count as dropped records.

## Programme time

- **Unpaused programme time.** Each record's `programme` holds `item_idx`, `order`, `offset_s` and `paused`.
  - The time for a film is the span of `offset_s` over its unpaused records, plus the gaps between them when both ends are unpaused and the offset advanced.
  - Records taken while paused count toward the "paused broadcasts" measure, not toward rates.
- **Film-minute bins.** One bin per minute of `offset_s` for each film, counting the broadcasts in it. Bins with no programme coverage are marked absent, not zero.

## Modules

- A member's module is its event `source`. Workspace-internal sources (`syneidesis`, `volition`) are counted separately and never as a faculty.

## Comparisons

- **main − control** at the same step, for scalar measures.
- **Film-minute profiles** are compared with Pearson correlation over the bins present in both, together with the bin count. Fewer than 30 shared bins means the correlation is reported as not computed.
- Nothing is tested for significance: the design has one being per line. The report says so.

## Output

- `report.json`: schema version, study id, plan hash, per-viewing measures, per-step comparisons, data-quality notes and the limits.
- `report.md`: the same, as tables. Both are written atomically.
- `analyse` can be re-run and overwrites the previous report.
