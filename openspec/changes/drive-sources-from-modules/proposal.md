# Drive-relevant sources come from the modules, not a hardcoded table

## Why

The goal factor of salience (`DriveRelevanceGoalScorer`, an engineering extension of paper §3.4.3) weights an event by whether its source tends to relieve the dominant Thymos drive. The drive-to-source table is hardcoded in `kaine/workspace/strategies.py` and names modules such as `mundus`, `praxis` and `vox` (complexity audit W8). A module renamed, added or rebuilt (the Paracosmic embodiment rebuild is coming) silently drops out of the table, and nothing checks that a named source exists.

## What changes

- **`BaseModule.relieves_drives`.** `BaseModule` gains the class attribute `relieves_drives: ClassVar[frozenset[str]]`, empty by default, which declares the drives its events tend to relieve. Each module declares its own tags. The union reproduces the current table exactly. The only non-module source, Volition (workspace scaffolding), is declared beside the scorer.
- **The scorer** takes its mapping by dependency injection (`drive_sources`), so the workspace layer still never imports `kaine.modules`. A pure helper, `build_drive_sources(tags_by_source)`, turns per-source tags into the per-drive table and adds the scaffolding source.
- **Boot** builds the mapping from the registered modules and passes it to the scorer. Disabled modules emit no events, so only registered modules matter.
- **Tests.** One test checks that the union of every module class's tags equals the previous table, so no behaviour changes. Another checks that every drive tag is one of the four Thymos drives.

## Impact

No behaviour change. The goal factor ships on its static negative control, and with `drive_relevance` selected the mapping equals the previous table.
