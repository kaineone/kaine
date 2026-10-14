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

The command never deletes a stream that is written now, and the preboot report warns while old-named streams remain. Run manifests written after the upgrade carry `"config_key_scheme": 2`, so their `config_digest` is not compared with an earlier run's as if the keys were the same. Going back to a release from before the rename is not supported; restore the backup taken before upgrading instead.

