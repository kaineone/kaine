# The modules

KAINE is built from modules that publish events to the bus, compete for access to the global workspace, and read its broadcasts. Each module sits behind a fixed interface, so a module can be replaced by one built on a different model or theory. This page lists every module, says which ones the base-thesis research profile turns on, and points to each module's page and to the configuration reference.

## Module roster

The shipped `[modules]` block in [`config/kaine.toml`](../../config/kaine.toml) has 17 flags: 14 cognitive modules, 2 embodiment helpers (Mundus and Perception), and `echo`, which is permanent test infrastructure.

| Module | Role | Enabled in `thesis_test` |
|---|---|---|
| [Audition](audition.md) | Raw hearing: predicts the next window's spectral encoding and the tone of detected speech, conditioned on the broadcast context. Speech-to-text is built and off by default. | Yes |
| [Chronos](chronos.md) | Temporal prediction: takes every broadcast as its input, predicts the next one, detects recurrence, and tracks the time since a voice was last heard. | Yes |
| [Echo](echo.md) | Test infrastructure: records every workspace snapshot and can publish `echo.ping`. | No |
| [Eidolon](eidolon.md) | Self-model: identity maintenance and drift detection over workspace sources. | No |
| [Empatheia](empatheia.md) | Social cognition: per-agent theory-of-mind models and familiarity tracking. | No |
| [Hypnos](hypnos.md) | Sleep analog: fatigue-triggered offline periods with welfare gates on operations that modify models. | Yes |
| [Lingua](lingua.md) | Output-only language organ: turns accessed content into speech and inner thought on Volition's intents. | Yes |
| [Mnemos](mnemos.md) | Episodic memory: a vector store of affect-tagged traces with replay gated by Hypnos. | No |
| [Mundus](mundus.md) | Embodiment control plane: routes perception and action through a pluggable body adapter. | No |
| [Nous](nous.md) | Reasoning: active-inference belief updating and policy selection. | No |
| [Perception](perception.md) | Perceptual-locus arbiter: keeps the physical and virtual loci mutually exclusive and gates switching between them. | No |
| [Phantasia](phantasia.md) | World model and imagination: predicts surprise and generates imagined scenarios during sleep. | No |
| [Praxis](praxis.md) | Effectors: executes actions only for effectors on the operator's whitelist. | No |
| [Soma](soma.md) | Interoception: predicts the host's substrate state, conditioned on the broadcast context, and accumulates fatigue and regulation advisories. | Yes |
| [Thymos](thymos.md) | Affective core: valence, drives, and arousal, the global gain on selection, the sensory apertures, and the access rate. | Yes |
| [Topos](topos.md) | Foveated vision: predicts the next clip embedding from earlier ones and the broadcast context. | Yes |
| [Vox](vox.md) | Voice output: synthesizes external speech with prosody modulated by Thymos. | No |

`echo` must stay disabled in production. `mundus` also needs `KAINE_MUNDUS_OPERATOR_APPROVED=1` before it leaves the default stub body.

Topos, Audition, Soma, and Chronos are the four predictive processors. In the base-thesis profile each one scales its prediction error by its own recent errors, reports an intensity graded by that ratio, and marks every report with a boolean `alert`. See each module's page and [The global workspace](../08-cognitive-cycle/global-workspace.md) for how the reports compete.

## Enabling and disabling modules

Every module is controlled by a flag under `[modules]` in `config/kaine.toml`. The shipped `config/kaine.toml` has every module flag off, but when no profile is selected the loader applies the base-thesis `thesis_test` profile automatically (`kaine/config.py`). The operator file merges last, and the first-run wizard writes its own `[modules]` table there, so a wizard-configured install runs the wizard's module set instead (see [Module defaults](../appendix-a-configuration/README.md#module-defaults)). Without an operator `[modules]` table, the entity runs the `thesis_test` module set. The workspace (Syneidesis) and action selection (Volition) are always on and have no module flags.

Modules that are off in `thesis_test` are built and tested in isolation and held. The module-addition study (the code calls it the ignition study, see [The module-ignition study](../15-experiments/ignition-study.md)) adds six of them one at a time, in the order Mnemos, Phantasia, Nous, Eidolon, Empatheia, Vox. Praxis, Perception, and Mundus join through an explicit order once an effector, a body, or an alternative sensor feed is attached, since on the reference host they would have nothing to work with.

## The base-thesis profile

The base-thesis profile in [`config/profiles/thesis_test.toml`](../../config/profiles/thesis_test.toml) is a research profile, not a deployment tier. It enables the four predictive processors in distinct signal domains (`soma`, `chronos`, `topos`, `audition`), the language organ (`lingua`), the affective core (`thymos`), and the sleep analog (`hypnos`, with voice alignment off):

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

The profile also turns on Topos foveation, Audition's general acoustic path, and Chronos's forward prediction, keeps speech-to-text off, sets the language organ to greedy decoding (`[lingua].temperature = 0.0`), and selects the seeded perception feed.

With no profile selected, `thesis_test` is loaded automatically, so a bare `python -m kaine.cycle` already uses it. You can also request it explicitly:

```bash
KAINE_PROFILE=thesis_test python -m kaine.cycle
# or
python -m kaine.cycle --profile thesis_test
```

In this profile the language organ is output-only. No transcript reaches the model as input, so everything it voices comes from the workspace. Enabling modules does not start an entity: the cycle refuses to boot unless `KAINE_CYCLE_OPERATOR_PRESENT=1` is set or an unattended or research supervision mode passes its gate (see [Operation](../06-operation/README.md) and [Preservation and the safety net](../11-preservation.md)).

For all module-specific configuration keys, see [Modules configuration](../appendix-a-configuration/modules.md).
