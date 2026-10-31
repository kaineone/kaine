# The modules

KAINE is built from modules that publish events to the bus, compete for access to the global workspace, and read its broadcasts. Modules exchange typed events and declare the streams they read, and a few control couplings are direct calls (see [Architecture](../02-architecture/README.md#event-bus)). Plugins can swap the models inside four modules at declared seams (see [Plugins and CL1](../19-plugins-and-cl1.md)); rebuilding a whole module on another model or theory means writing a module that meets both kinds of interface. This page lists every module, says which ones the first-configuration research profile turns on, and points to each module's page and to the configuration reference.

## Module roster

The shipped `[modules]` block in [`config/kaine.toml`](../../config/kaine.toml) has 17 flags: 14 cognitive modules, 2 embodiment helpers (the embodiment and perceptual locus modules), and `recorder`, which is permanent test infrastructure.

| Module | Role | Enabled in `first_configuration` |
|---|---|---|
| [Audition](audition.md) | Raw hearing: predicts the next window's spectral encoding and the tone of detected speech, conditioned on the broadcast context. Speech-to-text is built and off by default. | Yes |
| [Sequence](sequence.md) | Temporal prediction: takes every broadcast as its input, predicts the next one, detects recurrence, and tracks the time since a voice was last heard. | Yes |
| [Recorder](recorder.md) | Test infrastructure: records every workspace snapshot and can publish `recorder.ping`. | No |
| [Self-model](self-model.md) | Self-model: identity maintenance and drift detection over workspace sources. | No |
| [Social cognition](social-cognition.md) | Social cognition: per-channel tone-of-voice models with familiarity tracking; it attributes no mental states. | No |
| [Sleep](sleep.md) | Sleep analog: fatigue-triggered offline periods with welfare gates on operations that modify models. | Yes |
| [Language](language.md) | Language organ, which hears no speech: turns accessed content into speech and inner thought on Action selection's intents. | Yes |
| [Episodic memory](episodic-memory.md) | Episodic memory: a vector store of affect-tagged traces of each broadcast's coalition, with replay gated by Sleep; a recall reports how much came back, not the content. | No |
| [Embodiment](embodiment.md) | Embodiment control plane: routes perception and action through a pluggable body adapter. | No |
| [Planning](planning.md) | Planning: one-step active-inference belief updating and policy selection over four meta-actions. | No |
| [Perceptual locus](perceptual-locus.md) | Perceptual-locus arbiter: keeps the physical and virtual loci mutually exclusive and gates switching between them. | No |
| [World model](world-model.md) | World model and imagination: a latent recurrent model of the waking sequence of broadcast summaries that predicts surprise and generates imagined scenarios during sleep. | No |
| [Effectors](effectors.md) | Effectors: executes actions only for effectors on the operator's whitelist. | No |
| [Interoception](interoception.md) | Interoception: predicts the host's substrate state, conditioned on the broadcast context, and accumulates fatigue and regulation advisories. | Yes |
| [Affect](affect.md) | Affective core: valence, drives, and arousal, a global gain on access that also sets the sensory apertures and the access rate. It reads the processors' reports directly, accessed or not. | Yes |
| [Vision](vision.md) | Foveated vision: predicts the next clip embedding from earlier ones and the broadcast context. | Yes |
| [Vocal](vocal.md) | Voice output: synthesizes external speech with prosody modulated by Affect. | No |

`recorder` must stay disabled in production. `embodiment` also needs `KAINE_EMBODIMENT_OPERATOR_APPROVED=1` before it leaves the default stub body.

The vision, audition, interoception, and sequence modules are the four predictive processors. In the first-configuration profile each one scales its prediction error by its own recent errors, reports an intensity graded by that ratio, and marks every report with a boolean `alert`. See each module's page and [The global workspace](../08-cognitive-cycle/global-workspace.md) for how the reports compete.

## Enabling and disabling modules

Every module is controlled by a flag under `[modules]` in `config/kaine.toml`. The shipped `config/kaine.toml` has every module flag off, but when no profile is selected the loader applies the `first_configuration` profile automatically (`kaine/config.py`). The operator file merges last, and the first-run wizard writes its own `[modules]` table there, so a wizard-configured install runs the wizard's module set instead (see [Module defaults](../appendix-a-configuration/README.md#module-defaults)). Without an operator `[modules]` table, the entity runs the `first_configuration` module set. The workspace and the action selection module are always on and have no module flags.

Modules that are off in `first_configuration` are built and unit-tested, with the limits each page states, and held; they have not run together. The module-addition study (the code calls it the ignition study, see [The module-ignition study](../15-experiments/ignition-study.md)) adds six of them one at a time, in the order episodic memory, world model, planning, self-model, social cognition, vocal modules. The effectors, perceptual locus and embodiment modules join through an explicit order once an effector, a body, or an alternative sensor feed is attached, since on the reference host they would have nothing to work with.

## The first-configuration profile

The first-configuration profile in [`config/profiles/first_configuration.toml`](../../config/profiles/first_configuration.toml) is a research profile, not a deployment tier. It enables the four predictive processors in distinct signal domains (`interoception`, `sequence`, `vision`, `audition`), the language organ (`language`), the affective core (`affect`), and the sleep analog (`sleep`, with voice alignment off):

```toml
[modules]
interoception = true
sequence = true
vision = true
audition = true
language = true
affect = true
sleep = true
```

The profile also turns on the vision module's foveation, the audition module's general acoustic path, and the sequence module's forward prediction, keeps speech-to-text off, and selects the seeded perception feed. The language organ samples at the shipped temperature; study configurations set greedy decoding.

With no profile selected, `first_configuration` is loaded automatically, so a bare `python -m kaine.cycle` already uses it. You can also request it explicitly:

```bash
KAINE_PROFILE=first_configuration python -m kaine.cycle
# or
python -m kaine.cycle --profile first_configuration
```

In this profile no transcript reaches the language organ, so it hears no speech. Each utterance is triggered by an intent derived from an accessed broadcast and conditioned on that broadcast, a fixed persona and situation notes; its own utterances come back to it quoted when they are accessed, and the individuation probe samples it privately on fixed prompts. The wording is the pretrained organ's. Enabling modules does not start an entity: the cycle refuses to boot unless `KAINE_CYCLE_OPERATOR_PRESENT=1` is set or an unattended or research supervision mode passes its gate (see [Operation](../06-operation/README.md) and [Preservation and the safety net](../11-preservation.md)).

For all module-specific configuration keys, see [Modules configuration](../appendix-a-configuration/modules.md).
