# Module names

This table maps each old module name and developmental term, which older records and releases still use, to the name the paper uses.

| Old name | New name |
|---|---|
| Topos | Vision |
| Soma | Interoception |
| Chronos | Sequence |
| Thymos | Affect |
| Hypnos | Sleep |
| Mnemos | Episodic memory |
| Phantasia | World model |
| Lingua | Language |
| Vox | Vocal |
| Nous | Planning |
| Volition | Action selection |
| Eidolon | Self-model |
| Empatheia | Social cognition |
| Syneidesis | Workspace |
| Praxis | Effectors |
| Mundus | Embodiment |
| Perception (the locus arbiter) | Perceptual locus |
| Spot | Supervisor |
| Nexus | Dashboard |
| Echo | Recorder |
| gestation | developmental phase |
| gestational stimulus | developmental stimulus |
| womb | stimulus source |
| birth | maturation |
| being | entity |
| gestation entrainment marker | heartbeat entrainment marker |

## After upgrading across the rename

Configuration files, studies and plugins written with the old names keep working: each file that uses an old table, key or stream name is read under the new name and logs one deprecation line naming the release after which the old names stop being read. A file that sets both the old and the new name of the same table is refused.

The bus streams are renamed too, so the streams written before the upgrade stay in Redis under their old names. Nothing reads them after the upgrade except two history readers: the language module looks in the old sleep stream for the last sleep index when the new stream has none yet, and the dashboard's conversation history reads the old external-speech stream before the new one. Redis runs without eviction, so the old streams should be removed once the run has settled:

```bash
python -m kaine.bus.legacy_streams            # list every old name, its new name, length and memory
python -m kaine.bus.legacy_streams --delete   # delete them after a typed confirmation
```

The command never deletes a stream the current release writes, a key that is not a stream, or an old stream whose newest entry is less than ten minutes old by the Redis server's clock (a cycle or a study image from before the upgrade may still be writing it), and the preboot report warns while old-named streams remain. Run manifests written after the upgrade carry `"config_key_scheme": 2`, so their `config_digest` is not compared with an earlier run's as if the keys were the same. Going back to a release from before the rename is not supported; restore the backup taken before upgrading instead.

## Operator names

The operator-facing names follow the module names. Each old name keeps working until the alias release named in the deprecation line it logs:

- Environment variables such as `KAINE_NEXUS_TOKEN` and `KAINE_MUNDUS_OPERATOR_APPROVED` are read under their old names when the new ones (`KAINE_DASHBOARD_TOKEN`, `KAINE_EMBODIMENT_OPERATOR_APPROVED`) are unset. When the old and the new name are both set and differ, startup stops and names both variables without printing either value. `compose/kaine.yml` reads each dashboard variable from `compose/.env` under its new name first and its old name second.
- The command-line flags `--db-gestation`, `--gestation-budget-seconds` and `--serve-nexus` are accepted as hidden aliases of `--db-development`, `--development-budget-seconds` and `--serve-dashboard`.
- `pip install "kaine[nexus]"` installs the `dashboard` extra, and `python -m kaine.nexus` runs `python -m kaine.dashboard`.
- The dashboard accepts the old session-key header `X-Nexus-Session-Key` beside `X-Dashboard-Session-Key`, and the page moves what a browser stored under the old storage keys to the new ones on first load. Sessions live in memory, so the upgrade signs every browser out once.

The dashboard container is now `kaine-dashboard`. With compose, run `docker compose -f compose/kaine.yml up -d --remove-orphans` so the old `kaine-nexus` container stops and frees port 8088. With quadlet, run `systemctl --user stop kaine-nexus` first; `bash scripts/install-quadlet.sh` refuses while that service runs, then removes the old unit file it installed. Then run `systemctl --user daemon-reload` and `systemctl --user start kaine-dashboard`. The record volume keeps its name, so the recorded data stays where it is.
