## Why

`KAINE_Paper_v4.md` §3.3.1 specifies Topos as a predictive vision module: a frozen
DINOv2-small encoder plus **a small forward model that predicts the next frame's
latent from the current one**, where visual salience is driven by prediction
error ("unexpected visual change is salient; expected change is not"), and a
recurrent visual buffer integrates over time. Today Topos embeds frames and
publishes a raw cosine `change_score` — it detects change but does not predict it,
so steady, predictable motion is as salient as a genuine surprise.

## What Changes

- Add `kaine/modules/topos/forward.py`: a small learned forward model (CfC or a
  shallow MLP/GRU, CPU) predicting the next 384-d DINOv2 latent from the current
  latent + recurrent state. Adapts online with a tiny gradient step per frame.
- Salience becomes driven by **prediction error** `||z(t) − ẑ(t−1)||` rather than
  raw cosine change; the existing `change_score`/`habituation_score` remain on the
  payload for diagnostics continuity.
- Add a recurrent visual buffer (bounded deque of recent latents) feeding the
  forward model's temporal context.
- The DINOv2 encoder stays **frozen** (no fine-tuning pathway — preserves the
  §3.5 adversarial-input mitigation).
- `[topos]` config gains: `forward_model_units`, `prediction_error_window`,
  `visual_buffer_size`.

## Capabilities

### New Capabilities

- `topos-predictive`: the forward-model layer over the frozen DINOv2 encoder —
  next-latent prediction, prediction-error-driven salience, recurrent visual
  buffer.

### Modified Capabilities

None (the frozen encoder + change/habituation diagnostics are retained).

## Impact

- **Depends on:** `topos` (shipped). No new package (reuses `ncps`/torch).
- **Repo:** adds `kaine/modules/topos/forward.py`, tests; updates
  `config/kaine.toml`.
- **Perception locus:** unchanged — Topos still binds to whichever world the
  perception locus selects (Mundus virtual frames or the real camera).
