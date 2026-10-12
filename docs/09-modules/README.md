# The modules

KAINE is built from modules that publish events to the bus, compete for access to the global workspace, and read its broadcasts. Each module sits behind a fixed interface, so a module can be replaced by one built on a different model or theory. This page lists every module, says which ones the base-thesis research profile turns on, and points to each module's page and to the configuration reference.

## Module roster

The shipped `[modules]` block in [`config/kaine.toml`](../../config/kaine.toml) has 17 flags: 14 cognitive modules, 2 embodiment helpers (the embodiment and perceptual locus modules), and `echo`, which is permanent test infrastructure.

| Module | Role | Enabled in `thesis_test` |
|---|---|---|
| [Audition](audition.md) | Raw hearing: predicts the next window's spectral encoding and the tone of detected speech, conditioned on the broadcast context. Speech-to-text is built and off by default. | Yes |
| [Sequence](sequence.md) | Temporal prediction: takes every broadcast as its input, predicts the next one, detects recurrence, and tracks the time since a voice was last heard. | Yes |
| [Recorder](recorder.md) | Test infrastructure: records every workspace snapshot and can publish `echo.ping`. | No |
| [Self-model](self-model.md) | Self-model: identity maintenance and drift detection over workspace sources. | No |
| [Social cognition](social-cognition.md) | Social cognition: per-agent theory-of-mind models and familiarity tracking. | No |
| [Sleep](sleep.md) | Sleep analog: fatigue-triggered offline periods with welfare gates on operations that modify models. | Yes |
| [Language](language.md) | Output-only language organ: turns accessed content into speech and inner thought on Action selection's intents. | Yes |
| [Episodic memory](episodic-memory.md) | Episodic memory: a vector store of affect-tagged traces with replay gated by Sleep. | No |
| [Embodiment](embodiment.md) | Embodiment control plane: routes perception and action through a pluggable body adapter. | No |
| [Planning](planning.md) | Reasoning: active-inference belief updating and policy selection. | No |
| [Perceptual locus](perceptual-locus.md) | Perceptual-locus arbiter: keeps the physical and virtual loci mutually exclusive and gates switching between them. | No |
| [World model](world-model.md) | World model and imagination: predicts surprise and generates imagined scenarios during sleep. | No |
| [Effectors](effectors.md) | Effectors: executes actions only for effectors on the operator's whitelist. | No |
| [Interoception](interoception.md) | Interoception: predicts the host's substrate state, conditioned on the broadcast context, and accumulates fatigue and regulation advisories. | Yes |
| [Affect](affect.md) | Affective core: valence, drives, and arousal, the global gain on selection, the sensory apertures, and the access rate. | Yes |
| [Vision](vision.md) | Foveated vision: predicts the next clip embedding from earlier ones and the broadcast context. | Yes |
| [Vocal](vocal.md) | Voice output: synthesizes external speech with prosody modulated by Affect. | No |

`echo` must stay disabled in production. `mundus` also needs `KAINE_MUNDUS_OPERATOR_APPROVED=1` before it leaves the default stub body.

The vision, audition, interoception, and sequence modules are the four predictive processors. In the base-thesis profile each one scales its prediction error by its own recent errors, reports an intensity graded by that ratio, and marks every report with a boolean `alert`. See each module's page and [The global workspace](../08-cognitive-cycle/global-workspace.md) for how the reports compete.

## Enabling and disabling modules

Every module is controlled by a flag under `[modules]` in `config/kaine.toml`. The shipped `config/kaine.toml` has every module flag off, but when no profile is selected the loader applies the base-thesis `thesis_test` profile automatically (`kaine/config.py`). The operator file merges last, and the first-run wizard writes its own `[modules]` table there, so a wizard-configured install runs the wizard's module set instead (see [Module defaults](../appendix-a-configuration/README.md#module-defaults)). Without an operator `[modules]` table, the entity runs the `thesis_test` module set. The workspace and the action selection module are always on and have no module flags.

Modules that are off in `thesis_test` are built and tested in isolation and held. The module-addition study (the code calls it the ignition study, see [The module-ignition study](../15-experiments/ignition-study.md)) adds six of them one at a time, in the order episodic memory, world model, planning, self-model, social cognition, vocal modules. The effectors, perceptual locus and embodiment modules join through an explicit order once an effector, a body, or an alternative sensor feed is attached, since on the reference host they would have nothing to work with.

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

The profile also turns on the vision module's foveation, the audition module's general acoustic path, and the sequence module's forward prediction, keeps speech-to-text off, and selects the seeded perception feed. The language organ samples at the shipped temperature; study configurations set greedy decoding.

With no profile selected, `thesis_test` is loaded automatically, so a bare `python -m kaine.cycle` already uses it. You can also request it explicitly:

```bash
KAINE_PROFILE=thesis_test python -m kaine.cycle
# or
python -m kaine.cycle --profile thesis_test
```

In this profile the language organ is output-only. No transcript reaches the model as input, so everything it voices comes from the workspace. Enabling modules does not start an entity: the cycle refuses to boot unless `KAINE_CYCLE_OPERATOR_PRESENT=1` is set or an unattended or research supervision mode passes its gate (see [Operation](../06-operation/README.md) and [Preservation and the safety net](../11-preservation.md)).

For all module-specific configuration keys, see [Modules configuration](../appendix-a-configuration/modules.md).
