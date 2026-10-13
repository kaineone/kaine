# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

GENDER = "[vox].voice_gender must be one of 'any', 'female' or 'male'"
RETIRED = f"[thymos.coupling].{name} is retired"
SUMMARY = f"{source}:soma.report={value}"
SENTENCE = f"Soma reports wellness {value}"
TOML = """
[mnemos]
backend = "qdrant"
"""
VOLUME = "kaine-nexus-record"
HEADER = "X-Nexus-Session-Key"
LAYOUT = 'data-dashboard-layout="nexus"'
LABEL = f"[Phantasia] world-prediction error {value}"
INLINE = 'nexus = { host = "x" }\n'
WRITER = "soma = true"
LOG_EVENT = "spot.log"
