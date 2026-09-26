# Proposal — `ignition-analysis`

## Why

The module-ignition study leaves one ignition log per viewing: every workspace broadcast with its programme position and coalition, and no content. The question is how each added faculty changed what reaches the workspace while the entity watches the same films. That needs the same measures computed the same way for every viewing, compared main against control and step against step, with the study's limits stated next to the numbers.

## What changes

- **`python -m kaine.research.ignition_study analyse <study_dir>`**. It reads the study plan, `steps.jsonl` and each completed viewing's ignition log, decrypting when state encryption is on. It writes `analysis/report.json` and `analysis/report.md` in the study directory.
- **Per viewing, from its ignition log:**
  - broadcasts per minute of programme time. Programme time counts unpaused film time only, so Hypnos replay windows and freezes do not dilute the rate.
  - broadcasts per film-minute bin, for each film;
  - coalition size (mean, median, p90);
  - the share of broadcasts whose coalition contains each module, by the member `source`;
  - the salience distribution of members (mean, p50, p90) by module;
  - the inhibited share;
  - picture-to-sound drift: the clock offset minus the audio's delivered seconds, as median and max absolute, when recorded;
  - data quality: record count, gaps longer than 10 s of programme time, and the sink's dropped-record count when it was logged.
- **Per step:**
  - main minus control for every per-viewing measure;
  - the change from the previous step on each line;
  - the film-minute profile correlation between the lines and between consecutive steps.
- **A limits section, in every report:**
  - modules are added in one fixed order, so each effect is conditional on the earlier ones and on the being's history;
  - control removes familiarity, not order;
  - modules with no input channel on this host (Praxis, Perception, the Mundus stub) are expected nulls and are flagged when their share is zero.
- **Output is content-free:** counts, rates, shares and distributions only. No payload is read, because the log has none.

## Depends on

- `film-aligned-ignition-log` (the record format)
- `ignition-study-runner` (the layout and `steps.jsonl`)

## Impact

- New module `kaine/research/ignition_study/analysis.py` and an `analyse` subcommand. Read-only over the study's data.
