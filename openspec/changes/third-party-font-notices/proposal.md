## Why

`THIRD_PARTY_LICENSES.md` credits two fonts the dashboard does not ship,
Chakra Petch and Orbitron, and does not credit the three it does ship: Inter,
JetBrains Mono and Zen Dots. The fonts folder also carries one licence file,
`OFL.txt`, whose only copyright line is Zen Dots'. The SIL Open Font License
(condition 2) lets a font be redistributed only when each copy carries its
copyright notice and the licence. The Inter and JetBrains Mono subsets carry no
licence text in their own metadata, so as shipped they do not meet that
condition. The fonts README also says each font carries the licence in its name
table, which is true only for Zen Dots.

## What Changes

- `THIRD_PARTY_LICENSES.md` lists Inter 4.001, JetBrains Mono 2.211 and Zen
  Dots 1.000 with their exact copyright lines, OFL 1.1, the licence file that
  ships with each, and the upstream source. Chakra Petch and Orbitron go.
- `kaine/dashboard/static/fonts/` ships one licence file per font family, each
  a byte copy of that family's upstream licence file: `OFL-Inter.txt`,
  `OFL-JetBrainsMono.txt`, `OFL-ZenDots.txt`. This is how each family ships its
  own licence upstream, and it keeps every copyright notice next to the licence
  text it belongs to. `OFL.txt` goes, replaced by `OFL-ZenDots.txt`.
- The fonts README states which file carries which notice and corrects the
  name-table claim.
- A test checks that every font file in the folder is credited in
  `THIRD_PARTY_LICENSES.md` and covered by a shipped licence file that holds
  its copyright line, and that every font file the notices list exists.

## Capabilities

### Modified Capabilities

- `license-compliance`: vendored fonts ship their copyright notices and
  licence text, and the third-party notices match the files on disk.

## Impact

- Documentation and licence files only, plus one test. No runtime change: the
  CSS loads the same woff2 files.
