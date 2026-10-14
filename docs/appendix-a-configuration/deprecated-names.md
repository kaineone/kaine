# Deprecated names

The names below are the configuration, environment and command names from before the module rename. Each one is still read as its new name up to and including release 27.02, and logs a deprecation line naming that release when it is used. Later releases stop reading them, so rename them in your files before then. [Module names](../appendix-e-module-names.md) maps each old module name to its new one.

Plugin seams named after an old module (`oscillator.<old name>` or `<old name>.<seam>`) resolve to the new seam under the same rule.

## Configuration tables

| Old | New | Last release that reads it |
|---|---|---|
| `[topos]` | `[vision]` | 27.02 |
| `[soma]` | `[interoception]` | 27.02 |
| `[chronos]` | `[sequence]` | 27.02 |
| `[thymos]` | `[affect]` | 27.02 |
| `[hypnos]` | `[sleep]` | 27.02 |
| `[mnemos]` | `[episodic_memory]` | 27.02 |
| `[phantasia]` | `[world_model]` | 27.02 |
| `[lingua]` | `[language]` | 27.02 |
| `[vox]` | `[vocal]` | 27.02 |
| `[nous]` | `[planning]` | 27.02 |
| `[volition]` | `[action_selection]` | 27.02 |
| `[eidolon]` | `[self_model]` | 27.02 |
| `[empatheia]` | `[social_cognition]` | 27.02 |
| `[syneidesis]` | `[workspace]` | 27.02 |
| `[praxis]` | `[effectors]` | 27.02 |
| `[mundus]` | `[embodiment]` | 27.02 |
| `[perception]` | `[perceptual_locus]` | 27.02 |
| `[spot]` | `[supervisor]` | 27.02 |
| `[nexus]` | `[dashboard]` | 27.02 |
| `[echo]` | `[recorder]` | 27.02 |
| `[perception_feed.womb]` | `[perception_feed.stimulus_source]` | 27.02 |
| `[research_event_log.nexus_record]` | `[research_event_log.dashboard_record]` | 27.02 |

## Configuration keys

A key keeps its new name in every table that uses it.

| Old | New | Last release that reads it |
|---|---|---|
| `womb_ready_retry_seconds` | `stimulus_source_ready_retry_seconds` | 27.02 |
| `womb_check_seconds` | `stimulus_source_check_seconds` | 27.02 |
| `womb_loss_after_seconds` | `stimulus_source_loss_after_seconds` | 27.02 |
| `womb_arm_timeout_seconds` | `stimulus_source_arm_timeout_seconds` | 27.02 |
| `womb_presence_window_seconds` | `stimulus_source_presence_window_seconds` | 27.02 |
| `womb_prediction_error_ceiling` | `stimulus_source_prediction_error_ceiling` | 27.02 |
| `birth_transition_seconds` | `maturation_transition_seconds` | 27.02 |
| `chronos_stream` | `sequence_stream` | 27.02 |
| `hypnos_stream` | `sleep_stream` | 27.02 |
| `lingua_external_stream` | `language_external_stream` | 27.02 |
| `lingua_quiet_s` | `language_quiet_s` | 27.02 |
| `mnemos_stream` | `episodic_memory_stream` | 27.02 |
| `require_operator_ack_for_birth` | `require_operator_ack_for_maturation` | 27.02 |
| `salience_thymos_factor` | `salience_affect_factor` | 27.02 |
| `soma_stream` | `interoception_stream` | 27.02 |
| `thymos_state_stream` | `affect_state_stream` | 27.02 |
| `volition_stream` | `action_selection_stream` | 27.02 |
| `nous_step_burst` | `planning_step_burst` | 27.02 |
| `nexus_url` | `dashboard_url` | 27.02 |
| `eidolon_accuracy_interval_hours` | `self_model_accuracy_interval_hours` | 27.02 |
| `eidolon_accuracy` | `self_model_accuracy` | 27.02 |
| `nous_policy` | `planning_policy` | 27.02 |
| `topos` | `vision` | 27.02 |
| `soma` | `interoception` | 27.02 |
| `chronos` | `sequence` | 27.02 |
| `thymos` | `affect` | 27.02 |
| `hypnos` | `sleep` | 27.02 |
| `mnemos` | `episodic_memory` | 27.02 |
| `phantasia` | `world_model` | 27.02 |
| `lingua` | `language` | 27.02 |
| `vox` | `vocal` | 27.02 |
| `nous` | `planning` | 27.02 |
| `volition` | `action_selection` | 27.02 |
| `eidolon` | `self_model` | 27.02 |
| `empatheia` | `social_cognition` | 27.02 |
| `syneidesis` | `workspace` | 27.02 |
| `praxis` | `effectors` | 27.02 |
| `mundus` | `embodiment` | 27.02 |
| `nexus` | `dashboard` | 27.02 |
| `topos.out` | `vision.out` | 27.02 |
| `soma.out` | `interoception.out` | 27.02 |
| `chronos.out` | `sequence.out` | 27.02 |
| `thymos.out` | `affect.out` | 27.02 |
| `hypnos.out` | `sleep.out` | 27.02 |
| `mnemos.out` | `episodic_memory.out` | 27.02 |
| `phantasia.out` | `world_model.out` | 27.02 |
| `lingua.out` | `language.out` | 27.02 |
| `vox.out` | `vocal.out` | 27.02 |
| `nous.out` | `planning.out` | 27.02 |
| `volition.out` | `action_selection.out` | 27.02 |
| `eidolon.out` | `self_model.out` | 27.02 |
| `empatheia.out` | `social_cognition.out` | 27.02 |
| `syneidesis.out` | `workspace.out` | 27.02 |
| `praxis.out` | `effectors.out` | 27.02 |
| `mundus.out` | `embodiment.out` | 27.02 |
| `perception.out` | `perceptual_locus.out` | 27.02 |
| `spot.out` | `supervisor.out` | 27.02 |
| `nexus.out` | `dashboard.out` | 27.02 |
| `echo.out` | `recorder.out` | 27.02 |
| `gestation.out` | `development.out` | 27.02 |
| `gestational.out` | `developmental.out` | 27.02 |
| `gestating.out` | `developing.out` | 27.02 |
| `womb.out` | `stimulus_source.out` | 27.02 |
| `birth.out` | `maturation.out` | 27.02 |
| `being.out` | `entity.out` | 27.02 |
| `lingua.external` | `language.external` | 27.02 |
| `lingua.internal` | `language.internal` | 27.02 |
| `eidolon.self_model` | `self_model.document` | 27.02 |
| `volition_feedback.out` | `action_selection_feedback.out` | 27.02 |
| `intent.perception.switch` | `intent.perceptual_locus.switch` | 27.02 |
| `stage.gestation.womb_lost` | `stage.development.stimulus_source_lost` | 27.02 |
| `stage.birth.ready` | `stage.maturation.ready` | 27.02 |
| `nexus.snapshot` | `dashboard.snapshot` | 27.02 |

## Configuration values

| Old | New | Last release that reads it |
|---|---|---|
| `perception_feed.mode=womb` | `perception_feed.mode=stimulus_source` | 27.02 |
| `mnemos.collection_prefix=mnemos_` | `episodic_memory.collection_prefix=episodic_memory_` | 27.02 |
| `empatheia.collection=empatheia_agents` | `social_cognition.collection=social_cognition_agents` | 27.02 |

## Environment variables

| Old | New | Last release that reads it |
|---|---|---|
| `KAINE_NEXUS_TOKEN` | `KAINE_DASHBOARD_TOKEN` | 27.02 |
| `KAINE_NEXUS_ACCESS` | `KAINE_DASHBOARD_ACCESS` | 27.02 |
| `KAINE_NEXUS_ALLOWED_ORIGINS` | `KAINE_DASHBOARD_ALLOWED_ORIGINS` | 27.02 |
| `KAINE_NEXUS_CONVERSATION_ENABLED` | `KAINE_DASHBOARD_CONVERSATION_ENABLED` | 27.02 |
| `KAINE_NEXUS_EXTRA_HOSTS` | `KAINE_DASHBOARD_EXTRA_HOSTS` | 27.02 |
| `KAINE_NEXUS_HOST` | `KAINE_DASHBOARD_HOST` | 27.02 |
| `KAINE_NEXUS_HOST_PORT` | `KAINE_DASHBOARD_HOST_PORT` | 27.02 |
| `KAINE_NEXUS_NON_LOOPBACK_ALLOWED` | `KAINE_DASHBOARD_NON_LOOPBACK_ALLOWED` | 27.02 |
| `KAINE_NEXUS_PORT` | `KAINE_DASHBOARD_PORT` | 27.02 |
| `KAINE_NEXUS_PUBLISHED_PORT` | `KAINE_DASHBOARD_PUBLISHED_PORT` | 27.02 |
| `KAINE_NEXUS_READ_ONLY` | `KAINE_DASHBOARD_READ_ONLY` | 27.02 |
| `KAINE_MUNDUS_OPERATOR_APPROVED` | `KAINE_EMBODIMENT_OPERATOR_APPROVED` | 27.02 |

## Command-line flags

| Old | New | Last release that reads it |
|---|---|---|
| `--serve-nexus` | `--serve-dashboard` | 27.02 |
| `--db-gestation` | `--db-development` | 27.02 |
| `--gestation-budget-seconds` | `--development-budget-seconds` | 27.02 |

## Packages and commands

| Old | New | Last release that reads it |
|---|---|---|
| `kaine[nexus]` | `kaine[dashboard]` | 27.02 |
| `python -m kaine.nexus` | `python -m kaine.dashboard` | 27.02 |
| `python -m kaine.lifecycle.mnemos_recover` | `python -m kaine.lifecycle.episodic_memory_recover` | 27.02 |

The dashboard container and quadlet unit are renamed and are not read under their old names; see [Operator names](../appendix-e-module-names.md#operator-names) for the switch.
