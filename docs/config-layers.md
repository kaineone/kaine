# Configuration Layers

KAINE resolves its runtime configuration from several layers. Each layer has a specific job, and together they let you ship safe defaults while still giving operators room to adjust a deployment without touching source code.

## The layers

Configuration is applied in a fixed order. Later layers win when two layers set the same key.

1. Shipped defaults
2. Tier profile
3. Operator override file
4. Secrets file
5. Environment variables

### Shipped defaults

Every known key carries a default value inside the application. These defaults are safe, conservative choices meant to make a fresh checkout boot without any extra files. They exist so the system always has a complete configuration, even if nothing else is present. Treat them as the floor, not as production tuning.

### Tier profiles

A tier profile is a named bundle of settings aimed at a class of deployment, such as a small single-node install or a larger multi-node setup. Selecting a profile adjusts groups of related keys at once, so you do not have to tune each value by hand. A profile only overrides the keys it names. Everything else keeps the shipped default.

Pick a profile with the `tier` setting in your operator override file, or through the matching environment variable. Profiles are optional. If you never name one, defaults stand alone.

### Operator override file

The operator override file is where you record decisions that belong to your installation: host names, ports, feature toggles, log levels, and the tier profile you want. This file is meant to live in version control or configuration management. It should never contain credentials. Anything sensitive goes in the secrets file instead.

### Secrets file

Secrets sit in their own file so they can follow different handling rules than the rest of your configuration. Store it outside version control, restrict file permissions, and rotate it independently. Values from this layer override the operator file, which keeps a leaked override file from also leaking credentials.

### Environment variables

Environment variables have the highest precedence. They exist for short-lived adjustments: a one-off debug run, a container deployment, an emergency toggle. Because they beat every file, they are also the easiest layer to lose track of. If a setting surprises you at runtime, check the environment first.

The naming scheme is predictable. A key like `server.port` becomes `KAINE_SERVER_PORT`. Nested keys join their segments with underscores, and the whole name is uppercased and prefixed with `KAINE_`.

## Worked example

Suppose `workers.count` is set in three places:

- Shipped default: 2
- Operator override file: 4
- Environment variable `KAINE_WORKERS_COUNT`: 8

The running process uses 8, because the environment wins. Remove the variable and restart, and the value falls back to 4. Remove the override entry too, and you are back at the shipped default of 2. Resolution is deterministic, so you can always trace where a value came from by walking the layers in order.

## The reference file

The repository ships a complete, annotated reference configuration file. It lists every supported key, its default, its type, and a short description of what it controls. Use it as both documentation and a starting template.

Two habits make the reference file useful over time:

- Copy it as the skeleton for your operator override, then delete the keys you do not need to change. Remaining defaults stay visible as comments rather than as silent assumptions.
- When you upgrade KAINE, diff your override against the new reference file. New keys and renamed keys show up immediately.

The reference file is kept in sync with the code as part of the change process. If you add or alter a configuration key, update the reference in the same change.

## The validation command

Before you start a process against a new or edited configuration, run the validation command:

    kaine config validate --file path/to/your/config.yaml

Validation checks the file against the known schema. It reports unknown keys, wrong types, values outside allowed ranges, and secrets placed in the wrong file. A clean result means the file will load; it does not prove the values are right for your environment, so pair it with a staged rollout for meaningful changes.

Useful flags:

    kaine config validate --file config.yaml --strict
    kaine config validate --file config.yaml --print-resolved

The strict flag turns warnings into failures, which is a good default for continuous integration. The print-resolved flag shows the fully merged configuration after all layers are applied, with secrets masked, so you can confirm precedence behaves the way you expect before anything runs.

## Practical rules

- Keep secrets out of the operator file, even temporarily.
- Prefer an operator override entry over an environment variable for anything meant to last.
- Re-run validation after every upgrade.
- When a value looks wrong in production, walk the layers from the top down: environment, secrets, operator file, profile, defaults.