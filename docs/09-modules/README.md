# The modules

KAINE is built from modules that compete for the global workspace and publish back into it. This page lists every module, gives a one-line description, and shows which ones the base-thesis research profile turns on. Use it to find the right module page and the configuration reference.

## Module roster

The shipped `[modules]` block in [`config/kaine.toml`](../../config/kaine.toml) has 17 flags: 14 cognitive processors, 2 embodiment helpers, and `echo`, which is permanent test infrastructure.

| Module | Role | Enabled in `thesis_test` |
|---|---|---|
| [Audition](audition.md) | Hearing organ: general acoustic front end, with optional speech-to-text and vocal-emotion classification. | Yes |
| [Chronos](chronos.md) | Temporal-context organ: encodes workspace history and detects anomaly, rumination, and idle time. | Yes |
| [Echo](echo.md) | Test infrastructure: records every workspace snapshot and can publish `echo.ping`. | No |
| [Eidolon](eidolon.md) | Self-model organ: identity maintenance and workspace-source drift detection. | No |
| [Empatheia](empatheia.md) | Social-cognition organ: per-agent theory-of-mind models and familiarity tracking. | No |
| [Hypnos](hypnos.md) | Sleep and maintenance organ: fatigue-triggered cycles with welfare gates on model-modifying operations. | Yes |
| [Lingua](lingua.md) | Language organ: voice generator that speaks from the conscious workspace. | Yes |
| [Mnemos](mnemos.md) | Episodic memory organ: vector-embedding store with affect-tagged traces and Hypnos-gated replay. | No |
| [Mundus](mundus.md) | Body-agnostic embodiment control plane: routes perception and action through a pluggable adapter. | No |
| [Nous](nous.md) | Reasoning organ: active-inference belief updating and policy selection. | No |
| [Perception](perception.md) | Perceptual-locus arbiter: enforces physical-XOR-virtual mutual exclusion and gates locus switching. | No |
| [Phantasia](phantasia.md) | World-model and imagination organ: predicts surprise and generates imagined sleep scenarios. | No |
| [Praxis](praxis.md) | Effector organ: safety-gated execution of real-world actions for whitelisted effectors. | No |
| [Soma](soma.md) | Interoceptive organ: predictive substrate monitoring, fatigue accumulation, and homeostatic regulation. | Yes |
| [Thymos](thymos.md) | Affective organ: emotional state, drives, goals, and salience modulation. | Yes |
| [Topos](topos.md) | Visual-perception organ: encodes camera frames and detects scene change and habituation. | Yes |
| [Vox](vox.md) | Voice output organ: synthesizes external speech via TTS with Thymos-modulated prosody. | No |

`echo` must stay disabled in production. `mundus` additionally needs `KAINE_MUNDUS_OPERATOR_APPROVED=1` to leave the default stub body.

## Enabling and disabling modules

Every module is controlled by a flag under `[modules]` in `config/kaine.toml`. The shipped `config/kaine.toml` has every module flag off, but when no profile is selected the loader applies the base-thesis `thesis_test` profile automatically (`kaine/config.py`). The operator file merges last, and the first-run wizard writes its own `[modules]` table there, so a wizard-configured install runs the wizard's module set instead (see [Module defaults](../appendix-a-configuration/README.md#module-defaults)). Without an operator `[modules]` table, the entity is the `thesis_test` one. The workspace (Syneidesis) and action-selection (Volition) scaffolding are always on and are not module flags.

Modules that are off in `thesis_test` are built and tested but shipped disabled. They wait for a positive base-thesis result before they are enabled.

## The base-thesis profile

The base-thesis profile in [`config/profiles/thesis_test.toml`](../../config/profiles/thesis_test.toml) is a research profile, not a deployment tier. It enables the four diverse predictive processors the base thesis needs — soma, chronos, topos, and audition — plus the language organ (`lingua`), the affect organ (`thymos`), and Hypnos (`hypnos`, sleep and consolidation with voice alignment off):

```toml
[modules]
soma = true
chronos = true
topos = true
audition = true
lingua = true
thymos = true
hypnos = true
```

With no profile selected, `thesis_test` is loaded automatically, so a bare `python -m kaine.cycle` already uses it. You can also request it explicitly:

```bash
KAINE_PROFILE=thesis_test python -m kaine.cycle
# or
python -m kaine.cycle --profile thesis_test
```

In this profile the language organ is output-only: no transcript reaches the model as input, so it is not a chatbot. Even with modules enabled, the cycle refuses to boot without `KAINE_CYCLE_OPERATOR_PRESENT=1` or the research safety net.

For all module-specific configuration keys, see [Modules configuration](../appendix-a-configuration/modules.md).
