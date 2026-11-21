# Base voice profiles

Populated by a maturation run: each committed profile is a JSON file named
`<gguf_sha256>.json` containing at least:

    {"gguf_sha256": "...", "style_profile": {...}}

Until at least one profile exists, `load_base_profile` returns None and the
distinctiveness arm reports null (content-free). Generate via a supervised
maturation run of the module-ignition study (see docs/appendix-d-roadmap.md).
