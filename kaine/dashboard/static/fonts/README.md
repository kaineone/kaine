# Vendored web fonts

Served locally from `/static/fonts` — no runtime download and no external font
CDN, which is what `no-cloud-runtime` requires. `tests/test_nexus_routers.py`
asserts that every woff2 referenced by `style.css` exists here and that the three
brand families are present.

The Kaine brand type system:

| Face | Role | Copyright |
|---|---|---|
| **Zen Dots** | display — headers, uppercase labels | Copyright 2021 The Dots Project Authors (https://github.com/googlefonts/zen-dots), designed by Yoshimichi Ohira |
| **Inter** | UI and body | Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter) |
| **JetBrains Mono** | metadata and data | Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono) |

All three are licensed under the **SIL Open Font License, Version 1.1**. The
license text is in `OFL.txt`, and each font also carries it in its own name
table.

Inter and JetBrains Mono come from Fontsource (latin subset). Zen Dots is subset
to latin locally — a Modified Version under the OFL. Zen Dots declares no
Reserved Font Name, so the subset keeps the family name. See
`assets/fonts/README.md` in kaineone/brand for the rebuild command.

Zen Dots ships a **single weight**, declared in `style.css` as
`font-weight: 400 700` so the console's 600/700 display rules match the face
rather than rendering as synthetic bold.
