# Shipped configuration before the keys rename

Byte copies of `config/kaine.toml`, `config/profiles/*.toml`, `config/studies/*.toml`
and the kaine-cl1 example configuration as they were before the keys step renamed
config tables, keys and values. `tests/test_legacy_config_sweep.py` runs the rename
codemod's keys scope over these copies and checks that the config normalizer reads
each old file to exactly what the codemod writes, so every key the rename moves has
a reader alias. The codemod never rewrites this folder.
