## Context

The organ's prompt is `persona + awareness block + trigger`. The awareness block comes from `FaithfulRenderer` over the accessed coalition, and the trigger for self-initiated intents is the report policy's `about`. Both carried raw values, and the organ repeated them.

## Science

- Borg, G. A. V. (1982). Psychophysical bases of perceived exertion. *Medicine and Science in Sports and Exercise* 14(5), 377-381. https://doi.org/10.1249/00005768-198205000-00012 (verified on Crossref). Category-ratio scaling: people grade a felt magnitude with verbal anchors ("weak", "moderate", "strong") placed on a ratio scale, not with instrument values.
- Stevens, S. S. (1957). On the psychophysical law. *Psychological Review* 64(3), 153-181. https://doi.org/10.1037/h0046162 (verified on Crossref). Magnitude estimation: felt magnitude grows as a power of stimulus intensity, so the report of a quantity is a judgment on a subjective scale, not a copy of the physical value.
- Barrett, L. F. (2017). The theory of constructed emotion: an active inference account of interoception and categorization. *Social Cognitive and Affective Neuroscience* 12(1), 1-23. https://doi.org/10.1093/scan/nsw154 (verified on Crossref and PubMed, PMID 27798257). Interoceptive signals reach experience as categorized concepts, not as raw values.

Together these justify a small ordered set of verbal categories per quantity. The bins are coarse on purpose: four or five categories, as in a category scale, with the edges placed against each quantity's range in the code.

## Decisions

### Bins

Each table is `((upper_edge, word), ...)`. A value below the first edge gets the first word; a value equal to an edge falls in the higher bin; the last edge is infinity. A missing, boolean or non-finite value gets no word and its phrase is left out.

| Quantity | Input | Edges and words |
| --- | --- | --- |
| change | `change_score`, cosine distance between successive embeddings | < 0.01 barely changing, < 0.05 changing a little, < 0.2 changing noticeably, else changing sharply |
| familiarity | `habituation_score` in [0, 1] | < 0.3 new to me, < 0.7 somewhat familiar, else familiar |
| surprise | report salience in [0, 1] | < 0.5 faintly, < 0.7 noticeably, < 0.85 strongly, else sharply |
| prediction error | error over its running mean (`normalised_error`, or `prediction_error / mean_prediction_error`) | < 0.75 as I expected, < 1.5 a little unexpected, < 3.0 unexpected, else very unexpected |
| wellness | `wellness` in [0, 1] | < 0.4 unwell, < 0.7 a little off, < 0.9 well, else very well |
| fatigue | `fatigue_value / fatigue_threshold` (threshold 100 when absent) | < 0.25 rested, < 0.5 a little tired, < 0.8 tired, else very tired |
| arousal | in [0, 1] | < 0.2 very calm, < 0.4 calm, < 0.6 alert, < 0.8 stirred up, else very stirred up |
| valence | in [-1, 1] | < -0.5 bad, < -0.15 a little low, < 0.15 neither good nor bad, < 0.5 good, else very good |
| dominance | in [-1, 1] | < -0.5 helpless, < -0.15 a little unsure of myself, < 0.15 steady, < 0.5 in control, else firmly in control |
| anomaly | sequence z-score | < 1 steady, < 2 a little irregular, < 3 irregular, else very irregular |
| drive level | drive value in [0, 1] | < 0.2 barely any, < 0.5 a little, < 0.8 clear, else strong (0.8 is `STRONG_DRIVE_BAND`) |
| time since interaction | seconds | < 60 someone was with me just now, < 600 it has been a little while since anyone was with me, else it has been a long time since anyone was with me |
| certainty | planning belief confidence in [0, 1] | < 0.4 I doubt, < 0.7 I think, < 0.9 I believe, else I am sure |

The sequence module's temporal prediction error has no fixed scale and no running mean on its payload, so the felt line leaves it out; the anomaly word already grades the rhythm's surprise, and the value stays in the log sidecar.

### Where the values go

Two options: log a numeric rendering in place of the felt one, or keep the logged prompt and rendering as the organ saw them and add sidecar fields. The sidecar is cleaner. The `prompt` and `faithful_rendering` fields are the DPO prompt and chosen side and the input to the grounding measure, so they must match what the organ saw; a numeric `faithful_rendering` would score grounding against text the organ never read and would teach a later voice adaptation to recite numbers. So the record keeps them and adds `numeric_rendering` (the numeric rendering of the same coalition, with the same event limit and no character cap so it covers every event the felt block could show, heard speech redacted the same way) and `about_values` (the intent's values, for example `{"source": "vision", "type": "vision.report", "surprise": 0.588}`). Both fields are written only in felt mode, so a numeric-mode record is unchanged.

### about_kind

The language module treats `"felt"` and `"event"` alike (not heard, published as `user_input`). The new phrase is a number-free felt phrase, so it uses `"felt"`; numeric mode keeps `"event"`.

### Persona

Both modes get the reworded persona and guard; the old persona line is what the organ echoed. Numeric mode changes only in the system prompt; its awareness block and `about` are bit for bit the old ones.

### Defaults

The constructors default to `"numeric"` so direct callers and existing tests are unchanged; `config/kaine.toml` and the first_configuration profile set `"felt"`, so every configured boot gets the felt mode.

## Risks

- Coarse bins lose resolution in the organ's text. The values stay in the log sidecar and on the bus events, so audits lose nothing.
- A future template could leak a digit. The felt renderer replaces any felt line with a digit (outside quoted heard speech) by a number-free line for its source.
