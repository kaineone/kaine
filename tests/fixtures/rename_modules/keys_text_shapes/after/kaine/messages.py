# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

GENDER = "[vocal].voice_gender must be one of 'any', 'female' or 'male'"
RETIRED = f"[affect.coupling].{name} is retired"
SUMMARY = f"{source}:interoception.report={value}"
SENTENCE = f"Soma reports wellness {value}"
TOML = """
[episodic_memory]
backend = "qdrant"
"""
VOLUME = "kaine-nexus-record"
HEADER = "X-Nexus-Session-Key"
LAYOUT = 'data-dashboard-layout="nexus"'
LABEL = f"[Phantasia] world-prediction error {value}"
INLINE = 'dashboard = { host = "x" }\n'
WRITER = "interoception = true"
LOG_EVENT = "supervisor.log"
