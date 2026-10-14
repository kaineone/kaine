# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""
Single mapping table from old module names to functional names.

The codemod ``tools/maintainer/rename_modules.py`` and every runtime alias table
read this module. It imports nothing and uses only builtins. It is the only live
source file that spells the old module names. ``SCOPE_STATUS`` tracks which
codemod scopes are complete; the guard ``tests/test_module_names_guard.py`` reads it.
"""

SCOPES = ("prose", "identifiers", "keys", "operator", "persisted")

SCOPE_STATUS = {
    "prose": "done",
    "identifiers": "done",
    "keys": "done",
    "operator": "done",
    "persisted": "done",
}

# The last release that still reads old operator-facing names (config tables and
# keys, environment variables, CLI flags, plugin seams). Deprecation warnings name
# it. The rule: the second release after the one that ships the rename, and no
# earlier than 90 days after it. The rename ships in the first release after
# 26.06.0a1, which is 26.10 at the earliest; 90 days after the end of October 2026
# falls at the end of January 2027, so 27.02 is the first release name that meets
# the 90-day floor for a 26.10 release. functional-module-names-drop-aliases checks
# both conditions against the releases actually cut before it removes anything,
# and moves this value later if they are not met.
ALIAS_LAST_RELEASE = "27.02"

MODULES = {
    "topos": {
        "old_class": "Topos",
        "new_class": "Vision",
        "new_key": "vision",
        "new_prose": "Vision",
        "layer": "5a",
    },
    "soma": {
        "old_class": "Soma",
        "new_class": "Interoception",
        "new_key": "interoception",
        "new_prose": "Interoception",
        "layer": "5a",
    },
    "chronos": {
        "old_class": "Chronos",
        "new_class": "Sequence",
        "new_key": "sequence",
        "new_prose": "Sequence",
        "layer": "5a",
    },
    "thymos": {
        "old_class": "Thymos",
        "new_class": "Affect",
        "new_key": "affect",
        "new_prose": "Affect",
        "layer": "5b",
    },
    "hypnos": {
        "old_class": "Hypnos",
        "new_class": "Sleep",
        "new_key": "sleep",
        "new_prose": "Sleep",
        "layer": "5b",
    },
    "mnemos": {
        "old_class": "Mnemos",
        "new_class": "EpisodicMemory",
        "new_key": "episodic_memory",
        "new_prose": "Episodic memory",
        "layer": "5b",
    },
    "phantasia": {
        "old_class": "Phantasia",
        "new_class": "WorldModel",
        "new_key": "world_model",
        "new_prose": "World model",
        "layer": "5b",
    },
    "lingua": {
        "old_class": "Lingua",
        "new_class": "Language",
        "new_key": "language",
        "new_prose": "Language",
        "layer": "5c",
    },
    "vox": {
        "old_class": "Vox",
        "new_class": "Vocal",
        "new_key": "vocal",
        "new_prose": "Vocal",
        "layer": "5c",
    },
    "nous": {
        "old_class": "Nous",
        "new_class": "Planning",
        "new_key": "planning",
        "new_prose": "Planning",
        "layer": "5c",
    },
    "volition": {
        "old_class": "Volition",
        "new_class": "ActionSelection",
        "new_key": "action_selection",
        "new_prose": "Action selection",
        "layer": "5c",
    },
    "eidolon": {
        "old_class": "Eidolon",
        "new_class": "SelfModel",
        "new_key": "self_model",
        "new_prose": "Self-model",
        "layer": "5c",
    },
    "empatheia": {
        "old_class": "Empatheia",
        "new_class": "SocialCognition",
        "new_key": "social_cognition",
        "new_prose": "Social cognition",
        "layer": "5c",
    },
    "syneidesis": {
        "old_class": "Syneidesis",
        "new_class": "Workspace",
        "new_key": "workspace",
        "new_prose": "Workspace",
        "layer": "5c",
    },
    "praxis": {
        "old_class": "Praxis",
        "new_class": "Effectors",
        "new_key": "effectors",
        "new_prose": "Effectors",
        "layer": "5c",
    },
    "mundus": {
        "old_class": "Mundus",
        "new_class": "Embodiment",
        "new_key": "embodiment",
        "new_prose": "Embodiment",
        "layer": "5d",
    },
    "perception": {
        "old_class": "Perception",
        "new_class": "PerceptualLocus",
        "new_key": "perceptual_locus",
        "new_prose": "Perceptual locus",
        "layer": "5d",
    },
    "spot": {
        "old_class": "Spot",
        "new_class": "Supervisor",
        "new_key": "supervisor",
        "new_prose": "Supervisor",
        "layer": "5d",
    },
    "nexus": {
        "old_class": "Nexus",
        "new_class": "Dashboard",
        "new_key": "dashboard",
        "new_prose": "Dashboard",
        "layer": "5d",
    },
    "echo": {
        "old_class": "Echo",
        "new_class": "Recorder",
        "new_key": "recorder",
        "new_prose": "Recorder",
        "layer": "5d",
    },
}

DEVELOPMENTAL = {
    "gestation": {
        "old_class": "Gestation",
        "new_class": "Development",
        "new_key": "development",
        "new_prose": "development",
        "layer": "5d",
    },
    "gestational": {
        "old_class": "Gestational",
        "new_class": "Developmental",
        "new_key": "developmental",
        "new_prose": "developmental",
        "layer": "5d",
    },
    "gestating": {
        "old_class": "Gestating",
        "new_class": "Developing",
        "new_key": "developing",
        "new_prose": "developing",
        "layer": "5d",
    },
    "womb": {
        "old_class": "Womb",
        "new_class": "StimulusSource",
        "new_key": "stimulus_source",
        "new_prose": "stimulus source",
        "layer": "5d",
        "old_plural": "wombs",
        "new_plural": "stimulus_sources",
    },
    "birth": {
        "old_class": "Birth",
        "new_class": "Maturation",
        "new_key": "maturation",
        "new_prose": "maturation",
        "layer": "5d",
        "old_plural": "births",
        "new_plural": "maturations",
    },
    "being": {
        "old_class": "Being",
        "new_class": "Entity",
        "new_key": "entity",
        "new_prose": "entity",
        "layer": "5d",
        "old_plural": "beings",
        "new_plural": "entities",
    },
}

UI_GLOBS = (
    "kaine/nexus/static/*",
    "kaine/nexus/templates/*",
    "kaine/dashboard/static/*",
    "kaine/dashboard/templates/*",
    "tests/js/*",
)

MODULE_LIST_FILES = (
    "kaine/modules/perception/*",
    "kaine/modules/perceptual_locus/*",
    "kaine/boot/factories/perception.py",
    "kaine/boot/factories/perceptual_locus.py",
    "kaine/modules/echo.py",
    "kaine/modules/recorder.py",
    "kaine/boot/factories/echo.py",
    "kaine/boot/factories/recorder.py",
    "kaine/boot/registry.py",
    "kaine/bus/streams.py",
    "kaine/setup/steps.py",
    "kaine/setup/wizard_core.py",
    "kaine/setup/wizard_steps.py",
)

GUARDED = {
    "spot": {
        "rules": [
            {
                "action": "keep",
                "pattern": r"(?i)\bspot[- ]checks?\b",
                "why": "English: spot check",
            },
            {
                "action": "keep",
                "pattern": r"[Ss]pot[Ll]ight",
                "why": "three.js spot light",
            },
            {
                "action": "keep",
                "shapes": ["camel_lower"],
                "why": "camelCase such as spotLight",
            },
            {
                "action": "rename",
                "pattern": r"(?<![A-Za-z])Spot(?![a-z])",
                "why": "proper name or class component",
            },
            {
                "action": "rename",
                "contexts": ["py_name", "toml_header", "toml_key", "path"],
                "why": "identifier or key position",
            },
            {
                "action": "rename",
                "shapes": ["component", "segment"],
                "why": "spot_, _spot, spot. or a path segment",
            },
            {
                "action": "rename",
                "pattern": r"[\"']spot[\"']",
                "why": "module key string",
            },
            {
                "action": "rename",
                "pattern": r"\[spot[\].]",
                "why": "config table in any text",
            },
            {
                "action": "rename",
                "contexts": ["md_code"],
                "pattern": r"`spot`",
                "why": "module key in a code span",
            },
            {
                "action": "rename",
                "pattern": r"SPOT (?:RECOVERY|CRITICAL)",
                "why": "dashboard banner text; renamed in the operator step",
            },
            {
                "action": "rename",
                "pattern": r"invalid spot config",
                "why": "names the config table, renamed with it",
            },
            {
                "action": "keep",
                "pattern": r"[\"']spot: \{",
                "why": "freeze reason text stored in the control file",
            },
        ],
        "default": "queue",
    },
    "echo": {
        "rules": [
            {
                "action": "keep",
                "contexts": ["shell"],
                "why": "shell builtin",
            },
            {
                "action": "keep",
                "files": [
                    "*.sh",
                    "*.bash",
                    "*.yml",
                    "*.yaml",
                    "Dockerfile*",
                    "docker/*",
                    "quadlet/*",
                    ".github/*",
                    "scripts/*",
                ],
                "why": "shell, CI and container files",
            },
            {
                "action": "rename",
                "pattern": r"(?<![A-Za-z])EchoModule\b",
                "why": "module class",
            },
            {
                "action": "rename",
                "pattern": r"(?<![A-Za-z0-9])ECHO_[A-Z0-9_]+",
                "why": "module constant",
            },
            {
                "action": "rename",
                "pattern": r"kaine[./](?:modules|boot[./]factories)[./]echo(?![A-Za-z_])",
                "why": "module path",
            },
            {
                "action": "rename",
                "pattern": r"(?<![A-Za-z0-9_.])echo\.out\b",
                "why": "module stream",
            },
            {
                "action": "rename",
                "contexts": ["toml_header"],
                "pattern": r"^\s*\[\[?echo[\].]",
                "why": "config table",
            },
            {
                "action": "rename",
                "contexts": ["toml_key"],
                "toml_table": "modules",
                "why": "module flag",
            },
            {
                "action": "rename",
                "contexts": ["py_string"],
                "files": list(MODULE_LIST_FILES),
                "pattern": r"[\"']echo[\"']",
                "why": "module key in a module list",
            },
            {
                "action": "rename",
                "contexts": ["py_name"],
                "files": ["tests/test_phase_1_endtoend.py", "tests/systems/test_cycle_subsystem.py"],
                "pattern": r"(?<![A-Za-z0-9_])(?:echo_a|echo_b|EchoB|echo)(?![A-Za-z0-9_])",
                "why": "EchoModule instances and subclasses in these tests",
            },
            {
                "action": "rename",
                "contexts": ["py_string"],
                "pattern": r"[\"']echo[\"'](?=\s*:\s*(?:True|False|frozenset\())",
                "why": "module flag or a map keyed by module",
            },
            {
                "action": "rename",
                "pattern": r"\[\s*[\"']modules[\"']\s*\]\s*\[\s*[\"']echo[\"']\s*\]",
                "why": "module flag lookup",
            },
            {
                "action": "rename",
                "contexts": ["py_string"],
                "files": [
                    "tests/test_ignition_*.py",
                    "tests/test_study_and_overlay_consistency.py",
                    "tests/test_config_stream_wiring.py",
                    "tests/test_drive_sources_from_modules.py",
                    "tests/test_wizard_module_presets.py",
                    "tests/test_no_nonblocking_dollar_reads.py",
                    "tests/test_stream_registry_drift.py",
                ],
                "pattern": r"[\"']echo[\"']",
                "why": "module key in a module list",
            },
            {
                "action": "rename",
                "pattern": r"source\s*==\s*[\"']echo[\"']",
                "why": "the recorder module's event source",
            },
            {
                "action": "rename",
                "pattern": r"(?<![A-Za-z0-9_.-])echo\.ping\b",
                "why": "the recorder module's event type",
            },
            {
                "action": "rename",
                "pattern": r"\[modules\]\.echo\b",
                "why": "module flag",
            },
            {
                "action": "keep",
                "pattern": r"`\"echo\"`",
                "why": "the recorder's default message label value",
            },
            {
                "action": "rename",
                "contexts": ["md_code", "md_prose"],
                "files": [
                    "docs/09-modules/README.md",
                    "docs/09-modules/recorder.md",
                    "docs/04-getting-started/first-boot.md",
                    "docs/appendix-a-configuration/core.md",
                    "openspec/specs/module-pattern/spec.md",
                ],
                "pattern": r"(?<![A-Za-z0-9_.-])echo(?![A-Za-z0-9_-])",
                "why": "the recorder module key in module docs",
            },
            {
                "action": "keep",
                "pattern": r"(?<![A-Za-z0-9_])(?:EchoConditionedClient|_EchoModelClient|_NamedEcho)(?![A-Za-z0-9_])",
                "why": "echo as a verbatim repeat, not the recorder module",
            },
            {
                "action": "keep",
                "contexts": [
                    "py_name",
                    "py_string",
                    "py_text",
                    "comment",
                    "docstring",
                    "shell",
                    "md_code",
                    "md_prose",
                    "toml_string",
                    "toml_text",
                ],
                "why": "echo as a verbatim repeat, not the recorder module",
            },
        ],
        "default": "queue",
    },
    "perception": {
        "rules": [
            {
                "action": "keep",
                "pattern": r"perception_(?:feed|preview|state|transition|prng)",
                "why": "perception feed and friends",
            },
            {
                "action": "keep",
                "pattern": r"PERCEPTION_(?:FEED|PREVIEW|STATE|TRANSITION|PRNG)",
                "why": "feed and preview constants",
            },
            {
                "action": "keep",
                "pattern": r"perception\.transition",
                "why": "stimulus-source-to-world crossfade",
            },
            {
                "action": "keep",
                "pattern": r"kaine\[[^\]]*perception",
                "why": "pip extra",
            },
            {
                "action": "keep",
                "files": ["pyproject.toml"],
                "toml_table": "project.optional-dependencies",
                "why": "pip extra",
            },
            {
                "action": "keep",
                "contexts": [
                    "md_prose",
                    "comment",
                    "docstring",
                    "toml_comment",
                    "py_text",
                    "toml_text",
                ],
                "pattern": r"(?<![A-Za-z])perception(?![A-Za-z_.])",
                "why": "plain word",
            },
            {
                "action": "rename",
                "pattern": r"(?<![A-Za-z])PerceptionLocus",
                "why": "locus class",
            },
            {
                "action": "rename",
                "pattern": r"kaine[./](?:modules|boot[./]factories)[./]perception(?![A-Za-z_])",
                "why": "locus module path",
            },
            {
                "action": "rename",
                "contexts": ["toml_header"],
                "pattern": r"^\s*\[\[?perception[\].]",
                "why": "config table",
            },
            {
                "action": "rename",
                "contexts": ["toml_key"],
                "toml_table": "modules",
                "why": "module flag",
            },
            {
                "action": "rename",
                "contexts": ["py_string"],
                "files": list(MODULE_LIST_FILES),
                "pattern": r"[\"']perception[\"']",
                "why": "module key in a module list",
            },
            {
                "action": "rename",
                "pattern": r"(?<![A-Za-z0-9_.])perception\.(?:out|locus)\b",
                "why": "locus streams",
            },
            {
                "action": "rename",
                "pattern": r"intent\.perception\.switch",
                "why": "locus intent",
            },
            {
                "action": "rename",
                "pattern": r"state/perception/",
                "why": "locus state directory",
            },
            {
                "action": "rename",
                "contexts": ["py_name", "py_string"],
                "pattern": r"(?<![A-Za-z0-9_])make_perception(?![A-Za-z0-9_])",
                "why": "locus module factory",
            },
            {
                "action": "rename",
                "contexts": ["py_name", "py_string"],
                "pattern": r"(?<![A-Za-z0-9_])PERCEPTION_STREAM(?![A-Za-z0-9_])",
                "why": "locus module stream constant",
            },
            {
                "action": "rename",
                "contexts": ["py_name"],
                "files": ["tests/test_revive_each_module.py"],
                "pattern": r"(?<![A-Za-z0-9_])(?:_build_perception|_mutate_perception|test_roundtrip_perception)(?![A-Za-z0-9_])",
                "why": "locus module identifiers in revive tests",
            },
            {
                "action": "rename",
                "contexts": ["py_name"],
                "files": ["tests/test_perception_feed_integration.py", "tests/test_womb_feed_integration.py"],
                "pattern": r"(?<![A-Za-z0-9_])perception(?![A-Za-z0-9_])",
                "why": "PerceptionLocus local variable in integration tests",
            },
            {
                "action": "rename",
                "contexts": ["py_string"],
                "files": [
                    "kaine/evaluation/stream_registry.py",
                    "kaine/modules/world_model/encoder.py",
                    "kaine/research/ignition_study/analysis.py",
                    "tests/test_ignition_*.py",
                    "tests/test_study_and_overlay_consistency.py",
                    "tests/test_config_stream_wiring.py",
                    "tests/test_boot_wiring.py",
                    "tests/test_drive_sources_from_modules.py",
                    "tests/test_reduced_module_set_boot.py",
                    "tests/test_revive_each_module.py",
                    "tests/test_timing_dilation_phase2.py",
                    "tests/test_wizard_module_presets.py",
                    "tests/test_salience_factor_wiring.py",
                ],
                "pattern": r"[\"']perception[\"']",
                "why": "the locus module key in a module list or a map keyed by module",
            },
            {
                "action": "keep",
                "pattern": r"(?<![A-Za-z0-9_])_perception_banner(?![A-Za-z0-9_])",
                "why": "operator-facing template, not the locus module",
            },
            {
                "action": "keep",
                "pattern": r"source\s*=\s*=?\s*[\"']perception[\"']",
                "why": "the perception feed's own event source",
            },
            {
                "action": "keep",
                "pattern": r"CheckResult\(\s*[\"']perception[\"']",
                "why": "preboot check group",
            },
            {
                "action": "keep",
                "pattern": r"type_?\s*=\s*[\"']perception[\"']",
                "why": "an Audition event type",
            },
            {
                "action": "keep",
                "pattern": r"/diagnostics/perception\b",
                "why": "dashboard API route, renamed with the UI",
            },
            {
                "action": "keep",
                "pattern": r"\.\[perception\]",
                "why": "pip extra",
            },
            {
                "action": "keep",
                "files": [
                    "tests/test_container_deployment.py",
                    "tests/test_decommission_delete.py",
                ],
                "why": "state and tmpfs directory names",
            },
            {
                "action": "keep",
                "contexts": ["py_string"],
                "files": ["kaine/dashboard/diagnostics.py"],
                "why": "template context name, renamed with the UI",
            },
            {
                "action": "keep",
                "pattern": r"(?<![A-Za-z0-9_])PerceptionState(?![A-Za-z0-9_])",
                "why": "feed state class in kaine/perception_state.py",
            },
            {
                "action": "keep",
                "pattern": r"(?<![A-Za-z0-9_])check_perception(?![A-Za-z0-9_])",
                "why": "preboot sensor check",
            },
            {
                "action": "keep",
                "pattern": r"[\"']PERCEPTION[\"']",
                "why": "preboot group label",
            },
            {
                "action": "keep",
                "contexts": [
                    "py_name",
                    "path",
                    "md_code",
                    "md_prose",
                    "py_string",
                    "py_text",
                    "comment",
                    "docstring",
                    "shell",
                    "toml_string",
                    "toml_text",
                ],
                "why": "the perception subsystem, not the locus module",
            },
        ],
        "default": "queue",
    },
    "being": {
        "rules": [
            {
                "action": "keep",
                "pattern": r"(?i)\bhuman beings?\b",
                "why": "English: human being",
            },
            {
                "action": "keep",
                "pattern": r"(?i)\bwell[\s_-]?beings?\b",
                "why": "English: well-being",
            },
            {
                "action": "rename",
                "pattern": r"(?<![A-Za-z])beings\b",
                "why": "plural noun",
            },
            {
                "action": "rename",
                "pattern": r"(?<![A-Za-z])being's",
                "why": "possessive noun",
            },
            {
                "action": "rename",
                "shapes": ["component", "segment"],
                "why": "identifier component such as fork_being",
            },
            {
                "action": "rename",
                "contexts": ["py_name"],
                "why": "identifier",
            },
        ],
        "default": "keep",
    },
}

_MODULE_CLASSES = "Topos|Soma|Chronos|Thymos|Hypnos|Mnemos|Phantasia|Lingua|Vox|Nous|Volition|Eidolon|Empatheia|Syneidesis|Praxis|Mundus|Spot|Nexus|Echo|Audition"

# Dashboard JavaScript globals (window.NexusAuth, NexusBirth, ...).
_DASHBOARD_JS_GLOBALS = r"(?<![A-Za-z0-9_])Nexus(?:Auth|Birth|Caretaker|ChartRouting|Charts|Conn|Controls|Flow|Freeze|LiveSeries|Metrics|Perception|Preservation|Preview|RedAlert|RelTime|Reveal|Sections|Spot|SSE|Stream|Visibility|Vitals)(?![A-Za-z0-9_])"

# Explicit overrides for review-queue items are added by later pull requests.
RESOLUTIONS = [
    {
        "name": "nexus",
        "action": "rename",
        "pattern": r"kaine\.nexus\.sessionKey",
        "why": "browser storage key; renamed in the operator step, and the page migrates the old key",
    },
    {
        "name": "nexus",
        "action": "rename",
        "pattern": _DASHBOARD_JS_GLOBALS,
        "why": "dashboard JavaScript global; renamed in the operator step",
    },
    {
        "name": "spot",
        "action": "rename",
        "pattern": _DASHBOARD_JS_GLOBALS,
        "why": "dashboard JavaScript global; renamed in the operator step",
    },
    {
        "name": "birth",
        "action": "rename",
        "pattern": _DASHBOARD_JS_GLOBALS,
        "why": "dashboard JavaScript global; renamed in the operator step",
    },
    {
        "name": "perception",
        "action": "rename",
        "pattern": _DASHBOARD_JS_GLOBALS,
        "why": "dashboard JavaScript global; renamed in the operator step",
    },
    {
        "name": "perception",
        "action": "keep",
        "pattern": r"audition\.perception\b",
        "why": "an Audition event type, not the module",
    },
    {
        "name": "perception",
        "action": "keep",
        "pattern": r"PerceptionUnavailableError",
        "why": "an exception class about the senses",
    },
    {
        "name": "perception",
        "action": "rename",
        "pattern": r"\b(?:" + _MODULE_CLASSES + r")\**,? (?:and |or )?\**\[?Perception\b",
        "why": "named in a list of modules",
    },
    {
        "name": "perception",
        "action": "rename",
        "pattern": r"\bPerception\]?(?:\([^)]*\))?\**,? (?:and |or )?\**\[?(?:" + _MODULE_CLASSES + r")\b",
        "why": "named in a list of modules",
    },
    {
        "name": "perception",
        "action": "rename",
        "pattern": r"\[Perception\]\([^)]*perception\.md\)",
        "why": "link to the module page",
    },
    {
        "name": "perception",
        "action": "rename",
        "pattern": r"perception\.md\b",
        "contexts": ["md_prose", "path"],
        "files": ["docs/*"],
        "why": "the module page",
    },
    {
        "name": "perception",
        "action": "rename",
        "pattern": r"(?<![A-Za-z])Perception(?![a-z])",
        "contexts": ["md_prose"],
        "files": ["docs/09-modules/perception.md"],
        "why": "the module's own page",
    },
    {
        "name": "perception",
        "action": "rename",
        "pattern": r"\bPerception module\b",
        "why": "the module",
    },
    {
        "name": "perception",
        "action": "rename",
        "pattern": r"\bPerception arbitrates\b",
        "why": "the module",
    },
    {
        "name": "perception",
        "action": "rename",
        "pattern": r"\[modules\]\.perception\b",
        "why": "module flag",
    },
    {
        "name": "perception",
        "action": "keep",
        "pattern": r"(?<![A-Za-z])(?:[Pp]erception|PERCEPTION)(?![A-Za-z_]|\.[A-Za-z_])",
        "contexts": ["md_prose", "comment", "docstring", "toml_comment"],
        "why": "the faculty, not the module",
    },
    {
        "name": "echo",
        "action": "rename",
        "pattern": r"\b(?:" + _MODULE_CLASSES + r")\**,? (?:and |or )?\**Echo\b",
        "why": "named in a list of modules",
    },
    {
        "name": "echo",
        "action": "rename",
        "pattern": r"\[Echo\]\([^)]*echo\.md\)",
        "why": "link to the module page",
    },
    {
        "name": "echo",
        "action": "rename",
        "pattern": r"echo\.md\b",
        "contexts": ["md_prose", "path"],
        "files": ["docs/*"],
        "why": "the module page",
    },
    {
        "name": "echo",
        "action": "rename",
        "pattern": r"(?<![A-Za-z])Echo(?![a-z])",
        "contexts": ["md_prose"],
        "files": ["docs/09-modules/echo.md"],
        "why": "the module's own page",
    },
    {
        "name": "echo",
        "action": "rename",
        "pattern": r"\bEcho is always off\b|\bembodiment modules and Echo\b",
        "why": "the module",
    },
    {
        "name": "echo",
        "action": "rename",
        "contexts": ["comment", "docstring"],
        "files": [
            "kaine/setup/steps.py",
            "tests/test_drive_sources_from_modules.py",
            "tests/test_no_nonblocking_dollar_reads.py",
            "tests/test_phase_1_endtoend.py",
            "tests/test_stream_registry_drift.py",
            "tests/test_setup_wizard.py",
        ],
        "why": "the module, in code about modules",
    },
    {
        "name": "echo",
        "action": "keep",
        "contexts": ["md_prose", "comment", "docstring", "toml_comment"],
        "why": "the English word or the shell builtin",
    },
    {
        "name": "spot",
        "action": "keep",
        "pattern": r"(?i)\b(?:blind|sweet) spots?\b",
        "why": "English: blind spot, sweet spot",
    },
    {
        "name": "spot",
        "action": "rename",
        "contexts": ["comment", "docstring", "toml_comment"],
        "why": "the module, in code comments",
    },

    {
        "name": "phantasia",
        "action": "rename",
        "pattern": r"both parents carry a Phantasia world model",
        "why": "a quoted error message; renamed in the operator step",
    },
    {
        "name": "being",
        "action": "rename",
        "pattern": r"\bSeed being\b",
        "why": "the glossary term for the seeded entity; links already point at #seed-entity",
    },
    {
        "name": "nexus",
        "action": "rename",
        "pattern": r"nexus\.test\b",
        "why": "test hostname of the dashboard under test; renamed in the operator step",
    },
    {
        "name": "nexus",
        "action": "rename",
        "pattern": r"Requirement\(\s*\"[^\"]+\",\s*\"nexus\"",
        "why": "pip extra name; renamed in the operator step, with nexus kept as an alias extra",
    },
    {
        "name": "nexus",
        "action": "rename",
        "files": ["tests/test_extras.py"],
        "pattern": r"(?:\.extra\s*==\s*|extra=)\"nexus\"",
        "why": "pip extra name; renamed in the operator step, with nexus kept as an alias extra",
    },
    {
        "name": "spot",
        "action": "rename",
        "files": ["tests/test_unattended_gate.py"],
        "pattern": r"6_Spot_armed_and_self_tested",
        "why": "check key built from the operator-facing condition label; renamed with the label",
    },
    {
        "name": "nexus",
        "action": "rename",
        "pattern": r"X-Nexus-Session-Key",
        "why": "session-key HTTP header; renamed in the operator step, and the server still accepts the old header",
    },
    {
        "name": "nexus",
        "action": "rename",
        "pattern": r"nexus\.preservation\.events",
        "why": "browser storage key; renamed in the operator step, and the page migrates the old key",
    },
    # Operator step (PR 7): the review queue decided.
    {
        "name": "nexus",
        "action": "keep",
        "pattern": r"kaine-nexus-record",
        "why": "podman and compose volume name; renaming it would orphan the recorded data",
    },
    {
        "name": "perception",
        "action": "keep",
        "files": ["kaine/dashboard/static/*", "kaine/dashboard/templates/*"],
        "why": "the live perception subsystem the dashboard shows, not the locus module",
    },
    {
        "name": "perception",
        "action": "keep",
        "files": ["compose/*", "quadlet/*"],
        "pattern": r"#.*",
        "why": "a comment about the perception subsystem, not the locus module",
    },
    {
        "name": "spot",
        "action": "keep",
        "pattern": r"\blexical spot\b",
        "why": "English: a place in the text",
    },
    {
        "name": "spot",
        "action": "rename",
        "files": ["openspec/specs/unattended-boot/spec.md"],
        "pattern": r"event kind \"spot escalation\"",
        "why": "names the stored caretaker event kind, renamed in the persisted step",
    },
    {
        "name": "spot",
        "action": "rename",
        "files": [
            "kaine/cycle/*",
            "kaine/dashboard/static/*",
            "kaine/dashboard/templates/*",
            "tests/test_supervisor_*.py",
        ],
        "why": "the supervisor, in an operator-facing message, label or UI name",
    },
    {
        "name": "nexus",
        "action": "keep",
        "files": ["compose/*.yml"],
        "pattern": r"\$\{KAINE_DASHBOARD_[A-Z_]+:-\$\{KAINE_NEXUS_[A-Z_]+:-[^}]*\}\}",
        "why": "fallback to the old variable in an operator's compose/.env, read until the alias release",
    },
    {
        "name": "nexus",
        "action": "keep",
        "files": ["pyproject.toml"],
        "pattern": r"^nexus = \[\"kaine\[dashboard\]\"\]",
        "why": "the old pip extra, kept as an alias of the dashboard extra until the alias release",
    },
    {
        "name": "nexus",
        "action": "keep",
        "files": ["scripts/install-quadlet.sh"],
        "pattern": r"kaine-nexus\.container",
        "why": "the old unit the installer removes; the entry goes with the alias release",
    },
    {
        "name": "nexus",
        "action": "keep",
        "files": ["scripts/prepare-headless-host.sh"],
        "pattern": r"--serve-nexus(?:\)| is deprecated)",
        "why": "the old flag, accepted with a warning until the alias release",
    },
    {
        "name": "birth",
        "action": "rename",
        "files": ["tests/test_ignition_study_runner.py"],
        "pattern": r"wait_for_request\(state_dir, \"birth\"",
        "why": "the stored preservation reason the runner requests, renamed in the persisted step",
    },
    {
        "name": "gestation",
        "action": "rename",
        "pattern": r"\"locked_by\": \"gestation\"",
        "why": "the stored lock holder value, renamed in the persisted step",
    },
    {
        "name": "gestation",
        "action": "rename",
        "pattern": r"gestation_started_at",
        "why": "stored request field, renamed in the persisted step",
    },
    {
        "name": "birth",
        "action": "rename",
        "pattern": r"birth_bloom_ends_at",
        "why": "stored stage field, renamed in the persisted step",
    },
    # Persisted step (PR 8): the dashboard record's data directory keeps its name,
    # like the volume mounted on it, so recorded data is never split in two.
    {
        "name": "nexus",
        "action": "keep",
        "pattern": r"data/(?:evaluation/)?nexus_record",
        "why": "the dashboard record's data directory, mounted from the kaine-nexus-record volume",
    },
    # Persisted step (PR 8): the perception scratch directory moves with the
    # perceptual locus module's state directory.
    {
        "name": "perception",
        "action": "rename",
        "files": ["compose/*", "quadlet/*"],
        "pattern": r"/app/state/perception\b",
        "why": "the locus module's state directory, renamed in the persisted step",
    },
    {
        "name": "echo",
        "action": "keep",
        "pattern": r"\becho >>",
        "why": "the shell builtin",
    },
]

KEY_OVERRIDES = (
    ("eidolon.self_model", "self_model.document"),
    # kaine/workspace/syneidesis.py moves to kaine/workspace/core.py (PATH_OVERRIDES),
    # so its dotted import path and its path in text follow the same name.
    ("workspace.syneidesis", "workspace.core"),
    ("workspace/syneidesis", "workspace/core"),
    ("fork_being", "fork_entity"),
    ("PerceptionLocus", "PerceptualLocus"),
    ("perception.locus.", "perceptual_locus."),
    ("perception_locus", "perceptual_locus"),
    # The capability folder and name "spot-supervisor" would otherwise become a stutter.
    ("spot-supervisor", "supervisor"),
    # The locus page and capability name would otherwise become a stutter.
    ("perception-locus", "perceptual-locus"),
    # Identifiers that would otherwise stutter after the rename.
    ("hypnos_sleeping", "sleeping"),
    ("MnemosMemorySource", "EpisodicMemorySource"),
)

PHRASES = (
    ("gestation entrainment marker", "heartbeat entrainment marker"),
    ("gestational stimulus", "developmental stimulus"),
    ("Perception locus", "Perceptual locus"),
    ("perception locus", "perceptual locus"),
    ("a being", "an entity"),
    ("the being", "the entity"),
    ("each being", "each entity"),
    ("this being", "this entity"),
    ("every being", "every entity"),
    ("preserved being", "preserved entity"),
    ("a womb", "a stimulus source"),
    ("perception-locus.md", "perceptual-locus.md"),
)

PATH_OVERRIDES = {
    "kaine/workspace/syneidesis.py": "kaine/workspace/core.py",

    # The phantasia world_model module moved to kaine/modules/world_model/backend.py
    # in an earlier step, so its dotted import path and its path in text are updated.
    "kaine/modules/phantasia/world_model.py": "kaine/modules/world_model/backend.py",

    # Test files whose old name already said "sleep", "world_model", "effectors" or
    # "workspace" would otherwise stutter (test_sleep_sleep_pause.py).
    "tests/test_hypnos_sleep_cancellation.py": "tests/test_sleep_cancellation.py",
    "tests/test_hypnos_sleep_pause.py": "tests/test_sleep_pause.py",
    "tests/test_hypnos_sleep_replay_window.py": "tests/test_sleep_replay_window.py",
    "tests/test_phantasia_world_model.py": "tests/test_world_model_backend.py",
    "tests/test_praxis_effectors.py": "tests/test_effectors.py",
    "tests/test_workspace_syneidesis.py": "tests/test_workspace_core.py",
    "tests/test_perception_locus.py": "tests/test_perceptual_locus.py",
    # Test names that would otherwise read badly after the rename.
    "tests/test_developmental_gestation_lock.py": "tests/test_development_lock.py",
    "tests/test_womb_sources.py": "tests/test_stimulus_sources.py",
    # Keys ending in "/" are directory prefixes.
    "openspec/specs/spot-supervisor/": "openspec/specs/supervisor/",
    "docs/08-cognitive-cycle/perception-locus.md": "docs/08-cognitive-cycle/perceptual-locus.md",
    "openspec/specs/perception-locus/": "openspec/specs/perceptual-locus/",
}

PERSISTED_EXACT = {
    "gestation": "development",
    "gestation_started_at": "development_started_at",
    "womb_t_at_birth": "stimulus_source_t_at_maturation",
    "womb_seed": "stimulus_source_seed",
    "womb_params_digest": "stimulus_source_params_digest",
    "birth_bloom_ends_at": "maturation_bloom_ends_at",
    "hypnos_cursor": "sleep_cursor",
    "empatheia_agents": "social_cognition_agents",
    "mnemos_": "episodic_memory_",
    # Keys and values inside stored files; the keys run leaves them, the persisted step decides.
    "thymos_state": "affect_state",
    "hypnos_payload": "sleep_payload",
    "empatheia_deviation": "social_cognition_deviation",
    "nous_initiated": "planning_initiated",
    "nous_initiated_entry_ids": "planning_initiated_entry_ids",
    "nous_proposals_realized": "planning_proposals_realized",
    "nous_proposals_declined": "planning_proposals_declined",
    "nous_proposals_forwarded": "planning_proposals_forwarded",
    "unrealizable_nous_intents": "unrealizable_planning_intents",
    "eidolon_drift": "self_model_drift",
    "eidolon_drift_count": "self_model_drift_count",
    "eidolon_drift_signal": "self_model_drift_signal",
    "eidolon_identity_history_len": "self_model_identity_history_len",
    "eidolon_self_model_found": "self_model_found",
    "hypnos_adapters_present": "sleep_adapters_present",
    "soma_gain": "interoception_gain",
    "soma_error": "interoception_error",
    "topos_gain": "vision_gain",
    "topos_error": "vision_error",
    "soma_units": "interoception_units",
    "topos_units": "vision_units",
    "topos_lr": "vision_lr",
    "phantasia_cue": "world_model_cue",
    "lingua_revision": "language_revision",
    "topos_encoder": "vision_encoder",
    "womb_prediction_error": "stimulus_source_prediction_error",
    "womb_lost": "stimulus_source_lost",
    "womb_not_ready": "stimulus_source_not_ready",
    "no_womb_feed_configured": "no_stimulus_source_feed_configured",
    "spot_escalation": "supervisor_escalation",
    "forked_being": "forked_entity",
    "gestation_budget_seconds": "development_budget_seconds",
    "replay_mnemos": "replay_episodic_memory",
    "replay_phantasia": "replay_world_model",
    "eidolon_accuracy": "self_model_accuracy",
    "nous_policy": "planning_policy",
    # Stored tags: checkpoint headers, a reference and capture kind, a preservation
    # reason and a study outcome written to disk. The keys step leaves them.
    "kaine-phantasia-rssm-npz-v1": "kaine-world-model-rssm-npz-v1",
    "phantasia-encoder-v1": "world-model-encoder-v1",
    "birth": "maturation",
    "failed:gestation_unviable": "failed:development_unviable",
    # Episodic-memory collection names built from the stored "mnemos_" prefix.
    "mnemos_episodic": "episodic_memory_episodic",
    "mnemos_semantic": "episodic_memory_semantic",
    "mnemos_procedural": "episodic_memory_procedural",
    "mnemos_embedding_space": "episodic_memory_embedding_space",
    "mnemos_strength": "episodic_memory_strength",
    "mnemos_short_term": "episodic_memory_short_term",
}

# Strings an operator-facing template, page script or browser reads; they move with the UI strings in the operator step.
OPERATOR_EXACT = ("nexus_available", "nexus_error", "nexus_port", "nexus_running", "mnemos_store", "spot_state", "spot_escalated", "kaine_nexus_session")

REPO_TOP_DIRS = (
    "kaine",
    "tests",
    "plugins",
    "tools",
    "scripts",
    "docs",
    "openspec",
    "config",
    "quadlet",
    "compose",
    "docker",
    "eval_probes",
    ".github",
)

EXCLUDED_GLOBS = (
    "openspec/changes/archive/",
    "docs/records/",
    # archives and records are excluded at any depth, including OpenSpec trees inside plugins
    "*/openspec/changes/archive/*",
    "*/docs/records/*",
    "kaine/nexus/static/vendor/",
    "kaine/nexus/static/fonts/",
    "kaine/dashboard/static/vendor/",
    "kaine/dashboard/static/fonts/",
    "external/",
    "THIRD_PARTY_LICENSES.md",
    "unsloth_compiled_cache/",
    "kaine.egg-info/",
    "data/",
    "state/",
    "backups/",
    "secrets/",
    ".git/",
    "kaine/decision/schema.py",
    "kaine/decision/systemone.jinja",
    "eval_probes/",
    "kaine/modules/*/eval_probes/*.jsonl",
    "kaine/legacy_names.py",
    # The deprecated recovery-command shim keeps its old module name on purpose.
    "kaine/lifecycle/mnemos_recover.py",
    # The deprecated dashboard command shim keeps its old package name on purpose.
    "kaine/nexus/__init__.py",
    "kaine/nexus/__main__.py",
    # Stored field names stay byte-identical for good.
    "kaine/lifecycle/stored_field_names.py",
    "tests/fixtures/rename_modules/",
    # The pre-rename shipped configuration is preserved here for the sweep test.
    "tests/fixtures/legacy_config/",
    # These tests exercise the compatibility readers with the old names as literals,
    # so the codemod must never rewrite them.
    "tests/test_legacy_aliases.py",
    "tests/test_legacy_wiring_operator.py",
    "tests/test_legacy_wiring_readers.py",
    "tests/test_legacy_local_data.py",
    "tests/test_rename_state.py",
    "tests/test_rename_state_guards.py",
    "tests/test_legacy_keys_readers.py",
    "tests/test_legacy_reader_sites.py",
    "tests/test_legacy_reader_state.py",
    # 6b: the old-stream cleanup and the dry boot of old-named files use old names
    # on purpose.
    "tests/test_legacy_streams_cleanup.py",
    "tests/test_keys_flip_dry_boot.py",
    # PR 7: the browser storage helper and its tests name the old storage keys on
    # purpose, so a browser that still holds them is migrated.
    "kaine/dashboard/static/dashboard_legacy_storage.js",
    "tests/js/dashboard_legacy_storage_harness.js",
    "tests/test_dashboard_legacy_storage_js.py",
    # Golden pins on stored names that never change.
    "tests/test_stimulus_source_params_digest.py",
    # These documents record the rename itself and must keep the old names.
    "openspec/changes/functional-module-names-drop-aliases/",
    "docs/appendix-e-module-names.md",
    # The specs archived from the rename state how the old names are read, so they name them.
    "openspec/specs/module-naming/spec.md",
    "openspec/specs/configuration-loading/spec.md",
    "openspec/specs/developmental-stage/spec.md",
    "openspec/specs/entity-preservation/spec.md",
    # The changelog keeps its history in the names of its time, and its [Unreleased] entry names the deprecated ones.
    "CHANGELOG.md",
    # Generated from this table by tools/maintainer/gen_deprecated_names.py; it lists the old names on purpose.
    "docs/appendix-a-configuration/deprecated-names.md",
    # The agent tooling under .claude/ holds third-party OpenSpec command and skill templates.
    ".claude/",
    # Licence and notice files are never touched by the codemod,
    # because the licence text belongs to its author alone.
    "LICENSE*",
    "*/LICENSE*",
    "LICENSES/",
    "*/LICENSES/*",
    "NOTICE*",
    "*/NOTICE*",
    "COPYING*",
    "*/COPYING*",
    "COPYRIGHT*",
    "*/COPYRIGHT*",
)

EXCLUDED_TOML_KEYS = (
    ("individuation", "disclosure"),
)

# Collisions the codemod reports that are safe by construction. The sequence
# module's own file defines the class `Sequence` and binds no other `Sequence`
# (no typing or collections.abc import), so the class name shadows nothing there;
# every other file that binds `Sequence` gets the `SequenceModule` import alias.
ACCEPTED_COLLISIONS = [
    ("kaine/modules/sequence/module.py", "Sequence"),

    # Step 5b (affect, sleep, episodic memory, world model). Each was checked by
    # hand: the new name meets an existing token that is not the same binding, either
    # an import path segment beside asyncio.sleep or time.sleep, a keyword argument
    # (`world_model=`, `affect=`, `sleep=`) of another call, or a test-local
    # variable; ruff reports no redefinition after the run.
    ("kaine/cycle/individuation_runtime.py", "sleep"),
    ("kaine/modules/hypnos/job_queue_trainer.py", "sleep"),
    ("kaine/modules/hypnos/module.py", "sleep"),
    ("kaine/modules/hypnos/organ_adapter.py", "sleep"),
    ("kaine/modules/phantasia/__init__.py", "world_model"),
    ("kaine/modules/phantasia/module.py", "world_model"),
    ("tests/fake_training_stack.py", "sleep"),
    ("tests/test_cursor_follow_ups.py", "sleep"),
    ("tests/test_entity_preservation_revive.py", "world_model"),
    ("tests/test_heard_speech_never_leaks.py", "sleep"),
    ("tests/test_hypnos_module.py", "sleep"),
    ("tests/test_hypnos_phantasia_window.py", "affect"),
    ("tests/test_hypnos_phantasia_window.py", "sleep"),
    ("tests/test_hypnos_rest_requests.py", "sleep"),
    ("tests/test_hypnos_sleep_cancellation.py", "sleep"),
    ("tests/test_hypnos_sleep_replay_window.py", "affect"),
    ("tests/test_hypnos_sleep_replay_window.py", "sleep"),
    ("tests/test_hypnos_trigger.py", "sleep"),
    ("tests/test_lingua_module.py", "sleep"),
    ("tests/test_mnemos_trace_strength.py", "sleep"),
    ("tests/test_phantasia_module.py", "world_model"),
    ("tests/test_phantasia_numpy_engine.py", "world_model"),
    ("tests/test_phantasia_persistence.py", "world_model"),
    ("tests/test_preboot_correctness_phase35.py", "sleep"),
    ("tests/test_rename_state.py", "sleep"),
    ("tests/test_trainer_result_validation.py", "sleep"),
    ("tests/test_training_core.py", "sleep"),
    ("tests/test_voice_alignment_atomic_promotion.py", "sleep"),
    ("tests/test_voice_alignment_job_queue.py", "sleep"),
    ("tests/test_voice_alignment_organ_adapter.py", "sleep"),
    ("tests/test_voice_system_prompts.py", "sleep"),
    ("tests/test_world_model_identity.py", "world_model"),

    # Step 5c (language, vocal, planning, action selection, effectors, self-model,
    # social cognition, workspace). Each was checked by hand: the new name meets an
    # import path segment (kaine.workspace..., the effectors submodule), a keyword
    # argument of another call, an attribute of another object, or a test-local
    # variable; ruff reports no redefinition after the run.

    ("kaine/boot/wiring.py", "effectors"),
    ("kaine/cycle/__main__.py", "workspace"),
    ("kaine/evaluation/observers/ablation_observer.py", "workspace"),
    ("kaine/evaluation/redteam/harness.py", "effectors"),
    ("kaine/evaluation/redteam/harness.py", "workspace"),
    ("kaine/modules/praxis/__init__.py", "effectors"),
    ("kaine/modules/praxis/module.py", "effectors"),
    ("kaine/workspace/__init__.py", "workspace"),
    ("tests/test_dual_path_ablation.py", "workspace"),
    ("tests/test_individuation_probe_request.py", "self_model"),
    ("tests/test_planned_test_studies.py", "workspace"),
    ("tests/test_praxis_effectors.py", "effectors"),
    ("tests/test_praxis_module.py", "effectors"),
    ("tests/test_salience_factor_wiring.py", "workspace"),

    # Keys step (module key strings, config tables, streams). Each was checked by hand.
    # The new key already appears in the file with a different role and the two never
    # meet as keys of one mapping: a pip extra named "vision" beside the module key
    # (extras, wizard, setup steps), a device-map role "vision", a payload field
    # "affect" beside the affect module's event names (faithful templates, episodic
    # memory, their tests), the effectors module's own capability key "effectors",
    # the world-model backend sub-table [world_model.world_model] read inside its own
    # table, the dashboard package path segment, a "self_model" payload field the
    # research log strips, and a test class name.
    ("kaine/boot/factories/world_model.py", "world_model"),
    ("kaine/extras.py", "vision"),
    ("kaine/faithful/templates.py", "affect"),
    ("kaine/modules/effectors/module.py", "effectors"),
    ("kaine/modules/episodic_memory/module.py", "affect"),
    ("kaine/organ_server/device_map.py", "vision"),
    ("kaine/research/submission.py", "self_model"),
    ("kaine/setup/hardware_steps.py", "vision"),
    ("kaine/setup/web/app.py", "dashboard"),
    ("kaine/setup/wizard_core.py", "vision"),
    ("tests/test_boot_wiring.py", "effectors"),
    ("tests/test_boot_wiring.py", "world_model"),
    ("tests/test_dashboard_auth_js.py", "dashboard"),
    ("tests/test_dashboard_observability.py", "affect"),
    ("tests/test_dashboard_observability.py", "language"),
    ("tests/test_dashboard_routers.py", "dashboard"),
    ("tests/test_deterministic_cycle.py", "interoception"),
    ("tests/test_episodic_memory_module.py", "EpisodicMemory"),
    ("tests/test_episodic_memory_module.py", "affect"),
    # PR 7: the dashboard service and its pip extra share the name "dashboard".
    ("kaine/extras.py", "dashboard"),
    ("tests/test_extras.py", "dashboard"),
    ("tests/test_extras.py", "interoception"),
    ("tests/test_extras.py", "vision"),
    ("tests/test_faithful_templates.py", "affect"),
    ("tests/test_positive_control.py", "vision"),
    ("tests/test_research_event_log.py", "self_model"),
    ("tests/test_setup_device_map.py", "vision"),
    ("tests/test_setup_wizard.py", "vision"),

    # Step 6b (keys). The decommission registry and its tests name locations by
    # functional keys ("language", "self_model", "world_model",
    # "episodic_memory.sqlite") and bundle directories ("locations/world_model");
    # the renamed config tables meet those strings only as different roles (a
    # dotted config key or a module-name list), never in one mapping.
    ("kaine/lifecycle/decommission_locations.py", "language"),
    ("kaine/lifecycle/decommission_locations.py", "self_model"),
    ("kaine/lifecycle/decommission_locations.py", "world_model"),
    ("tests/test_decommission_coverage.py", "episodic_memory"),
    ("tests/test_decommission_end_to_end.py", "episodic_memory"),
    ("tests/test_decommission_locations.py", "episodic_memory"),
    ("tests/test_world_model_persistence.py", "world_model"),
]

SURVEY_EXTRA = (
    ("audition", "audition (unchanged)"),
    ("workspace", "workspace (target)"),
)

# The survey measures the tree as it was before the rename, so these keep the old paths.
SURVEY_UI_PREFIXES = (
    "kaine/nexus/static/",
    "kaine/nexus/templates/",
    "kaine/dashboard/static/",
    "kaine/dashboard/templates/",
)
SURVEY_THIRD_PARTY_PREFIXES = (
    "kaine/nexus/static/vendor/",
    "kaine/nexus/static/fonts/",
    "kaine/dashboard/static/vendor/",
    "kaine/dashboard/static/fonts/",
    "external/",
    "unsloth_compiled_cache/",
    "THIRD_PARTY_LICENSES.md",
)

GUARD_NAMES = tuple(
    sorted(e["old_class"] for k, e in MODULES.items() if k not in GUARDED)
)

# Identifiers built on an old module key that stay for good. The dashboard record keeps
# its data directory name because the record volume is mounted on it.
GUARD_KEPT_IDENTIFIERS = ("nexus_record",)

CONFIG_TABLES = tuple(
    {"old": k, "new": e["new_key"], "scope": "keys"} for k, e in MODULES.items()
) + (
    {"old": "perception_feed.womb", "new": "perception_feed.stimulus_source", "scope": "keys"},
    {"old": "research_event_log.nexus_record", "new": "research_event_log.dashboard_record", "scope": "keys"},
)

CONFIG_KEYS = (
    {"old": "womb_ready_retry_seconds", "new": "stimulus_source_ready_retry_seconds", "scope": "keys"},
    {"old": "womb_check_seconds", "new": "stimulus_source_check_seconds", "scope": "keys"},
    {"old": "womb_loss_after_seconds", "new": "stimulus_source_loss_after_seconds", "scope": "keys"},
    {"old": "womb_arm_timeout_seconds", "new": "stimulus_source_arm_timeout_seconds", "scope": "keys"},
    {"old": "womb_presence_window_seconds", "new": "stimulus_source_presence_window_seconds", "scope": "keys"},
    {"old": "womb_prediction_error_ceiling", "new": "stimulus_source_prediction_error_ceiling", "scope": "keys"},
    {"old": "birth_transition_seconds", "new": "maturation_transition_seconds", "scope": "keys"},
    {"old": "chronos_stream", "new": "sequence_stream", "scope": "keys"},
    {"old": "hypnos_stream", "new": "sleep_stream", "scope": "keys"},
    {"old": "lingua_external_stream", "new": "language_external_stream", "scope": "keys"},
    {"old": "lingua_quiet_s", "new": "language_quiet_s", "scope": "keys"},
    {"old": "mnemos_stream", "new": "episodic_memory_stream", "scope": "keys"},
    {"old": "require_operator_ack_for_birth", "new": "require_operator_ack_for_maturation", "scope": "keys"},
    {"old": "salience_thymos_factor", "new": "salience_affect_factor", "scope": "keys"},
    {"old": "soma_stream", "new": "interoception_stream", "scope": "keys"},
    {"old": "thymos_state_stream", "new": "affect_state_stream", "scope": "keys"},
    {"old": "volition_stream", "new": "action_selection_stream", "scope": "keys"},
    {"old": "nous_step_burst", "new": "planning_step_burst", "scope": "keys"},
    {"old": "nexus_url", "new": "dashboard_url", "scope": "keys"},
    {"old": "eidolon_accuracy_interval_hours", "new": "self_model_accuracy_interval_hours", "scope": "keys"},
    # [evaluation] switches named like their sidecar directories; they move with
    # the persisted step.
    {"old": "eidolon_accuracy", "new": "self_model_accuracy", "scope": "persisted"},
    {"old": "nous_policy", "new": "planning_policy", "scope": "persisted"},
)

# Module keys used as keys inside other tables (for example [evaluation.observers] or a plugin's backend table).
CONFIG_KEYS = CONFIG_KEYS + tuple(
    {"old": k, "new": e["new_key"], "scope": "keys"} for k, e in MODULES.items() if k not in GUARDED
)

CONFIG_VALUES = (
    {"old": "perception_feed.mode=womb", "new": "perception_feed.mode=stimulus_source", "scope": "keys"},
    {"old": "mnemos.collection_prefix=mnemos_", "new": "episodic_memory.collection_prefix=episodic_memory_", "scope": "persisted"},
    {"old": "empatheia.collection=empatheia_agents", "new": "social_cognition.collection=social_cognition_agents", "scope": "persisted"},
)

ENV_VARS = (
    {"old": "KAINE_NEXUS_TOKEN", "new": "KAINE_DASHBOARD_TOKEN", "scope": "operator"},
    {"old": "KAINE_NEXUS_ACCESS", "new": "KAINE_DASHBOARD_ACCESS", "scope": "operator"},
    {"old": "KAINE_NEXUS_ALLOWED_ORIGINS", "new": "KAINE_DASHBOARD_ALLOWED_ORIGINS", "scope": "operator"},
    {"old": "KAINE_NEXUS_CONVERSATION_ENABLED", "new": "KAINE_DASHBOARD_CONVERSATION_ENABLED", "scope": "operator"},
    {"old": "KAINE_NEXUS_EXTRA_HOSTS", "new": "KAINE_DASHBOARD_EXTRA_HOSTS", "scope": "operator"},
    {"old": "KAINE_NEXUS_HOST", "new": "KAINE_DASHBOARD_HOST", "scope": "operator"},
    {"old": "KAINE_NEXUS_HOST_PORT", "new": "KAINE_DASHBOARD_HOST_PORT", "scope": "operator"},
    {"old": "KAINE_NEXUS_NON_LOOPBACK_ALLOWED", "new": "KAINE_DASHBOARD_NON_LOOPBACK_ALLOWED", "scope": "operator"},
    {"old": "KAINE_NEXUS_PORT", "new": "KAINE_DASHBOARD_PORT", "scope": "operator"},
    {"old": "KAINE_NEXUS_PUBLISHED_PORT", "new": "KAINE_DASHBOARD_PUBLISHED_PORT", "scope": "operator"},
    {"old": "KAINE_NEXUS_READ_ONLY", "new": "KAINE_DASHBOARD_READ_ONLY", "scope": "operator"},
    {"old": "KAINE_MUNDUS_OPERATOR_APPROVED", "new": "KAINE_EMBODIMENT_OPERATOR_APPROVED", "scope": "operator"},
)

COMPOSE_VARS = (
    {"old": "NEXUS_HOST_PORT", "new": "DASHBOARD_HOST_PORT", "scope": "operator"},
    {"old": "NEXUS_EXTRA_HOSTS", "new": "DASHBOARD_EXTRA_HOSTS", "scope": "operator"},
    {"old": "NEXUS_TOKEN", "new": "DASHBOARD_TOKEN", "scope": "operator"},
    {"old": "NEXUS_ACCESS", "new": "DASHBOARD_ACCESS", "scope": "operator"},
)

TEST_ENV_VARS = (
    {"old": "KAINE_TOPOS_RUN_REAL_ENCODER", "new": "KAINE_VISION_RUN_REAL_ENCODER", "scope": "operator"},
    {"old": "KAINE_NOUS_RUN_REAL_PYMDP", "new": "KAINE_PLANNING_RUN_REAL_PYMDP", "scope": "operator"},
    {"old": "KAINE_NOUS_RUN_REAL_NAR", "new": "KAINE_PLANNING_RUN_REAL_NAR", "scope": "operator"},
    {"old": "KAINE_VOX_RUN_REAL", "new": "KAINE_VOCAL_RUN_REAL", "scope": "operator"},
    {"old": "KAINE_LINGUA_RUN_REAL_CHAT", "new": "KAINE_LANGUAGE_RUN_REAL_CHAT", "scope": "operator"},
)

CLI_FLAGS = (
    {"old": "--serve-nexus", "new": "--serve-dashboard", "scope": "operator"},
    {"old": "--db-gestation", "new": "--db-development", "scope": "operator"},
    {"old": "--gestation-budget-seconds", "new": "--development-budget-seconds", "scope": "operator"},
)

PLUGIN_SEAMS = tuple(
    {"old": f"oscillator.{k}", "new": f"oscillator.{e['new_key']}", "scope": "keys"}
    for k, e in MODULES.items()
) + (
    {"old": "soma.forward_model", "new": "interoception.forward_model", "scope": "keys"},
    {"old": "chronos.network", "new": "sequence.network", "scope": "keys"},
    {"old": "nous.engine", "new": "planning.engine", "scope": "keys"},
    {"old": "nous.engine_wrapper", "new": "planning.engine_wrapper", "scope": "keys"},
)

STREAM_NAMES = tuple(
    {"old": f"{k}.out", "new": f"{e['new_key']}.out", "scope": "keys"}
    for k, e in MODULES.items()
) + tuple(
    {"old": f"{k}.out", "new": f"{e['new_key']}.out", "scope": "keys"}
    for k, e in DEVELOPMENTAL.items()
) + (
    {"old": "lingua.external", "new": "language.external", "scope": "keys"},
    {"old": "lingua.internal", "new": "language.internal", "scope": "keys"},
    {"old": "eidolon.self_model", "new": "self_model.document", "scope": "keys"},
    {"old": "volition_feedback.out", "new": "action_selection_feedback.out", "scope": "keys"},
    {"old": "intent.perception.switch", "new": "intent.perceptual_locus.switch", "scope": "keys"},
    {"old": "stage.gestation.womb_lost", "new": "stage.development.stimulus_source_lost", "scope": "keys"},
    {"old": "stage.birth.ready", "new": "stage.maturation.ready", "scope": "keys"},
    {"old": "nexus.snapshot", "new": "dashboard.snapshot", "scope": "keys"},
)

# Bus event types whose spelling looks like a file name; they move with the keys step.
EVENT_TYPES = (
    {"old": "spot.log", "new": "supervisor.log", "scope": "keys"},
)

# Stream names used as keys (the [bus.per_stream_maxlen] table).
CONFIG_KEYS = CONFIG_KEYS + tuple(
    {"old": e["old"], "new": e["new"], "scope": e["scope"]} for e in STREAM_NAMES
)

RECORD_FIELDS = (
    {"old": "thymos_state", "new": "affect_state", "scope": "persisted"},
    {"old": "gestation_started_at", "new": "development_started_at", "scope": "persisted"},
    {"old": "hypnos_payload", "new": "sleep_payload", "scope": "persisted"},
    {"old": "empatheia_deviation", "new": "social_cognition_deviation", "scope": "persisted"},
    {"old": "nous_initiated", "new": "planning_initiated", "scope": "persisted"},
    {"old": "nous_initiated_entry_ids", "new": "planning_initiated_entry_ids", "scope": "persisted"},
    {"old": "nous_proposals_realized", "new": "planning_proposals_realized", "scope": "persisted"},
    {"old": "nous_proposals_declined", "new": "planning_proposals_declined", "scope": "persisted"},
    {"old": "nous_proposals_forwarded", "new": "planning_proposals_forwarded", "scope": "persisted"},
    {"old": "unrealizable_nous_intents", "new": "unrealizable_planning_intents", "scope": "persisted"},
    {"old": "eidolon_drift_count", "new": "self_model_drift_count", "scope": "persisted"},
    {"old": "eidolon_drift_signal", "new": "self_model_drift_signal", "scope": "persisted"},
    {"old": "eidolon_identity_history_len", "new": "self_model_identity_history_len", "scope": "persisted"},
    {"old": "eidolon_self_model_found", "new": "self_model_found", "scope": "persisted"},
    {"old": "hypnos_adapters_present", "new": "sleep_adapters_present", "scope": "persisted"},
    {"old": "phantasia_cue", "new": "world_model_cue", "scope": "persisted"},
    {"old": "womb_prediction_error", "new": "stimulus_source_prediction_error", "scope": "persisted"},
) + tuple(
    {"old": k, "new": e["new_key"], "scope": "keys"} for k, e in MODULES.items()
)

SIDECAR_DIRS = (
    {"old": "eidolon_accuracy", "new": "self_model_accuracy", "scope": "keys"},
    {"old": "empatheia", "new": "social_cognition", "scope": "keys"},
    {"old": "nous_policy", "new": "planning_policy", "scope": "keys"},
)

STATE_PATHS = (
    {"old": "mnemos/mnemos.db", "new": "episodic_memory/episodic_memory.db", "scope": "persisted"},
    {"old": "mnemos/store_health.json", "new": "episodic_memory/store_health.json", "scope": "persisted"},
    {"old": "lingua/intent_expression.jsonl", "new": "language/intent_expression.jsonl", "scope": "persisted"},
    {"old": "lingua/utterance_outcomes.jsonl", "new": "language/utterance_outcomes.jsonl", "scope": "persisted"},
    {"old": "eidolon/self_model.json", "new": "self_model/self_model.json", "scope": "persisted"},
    {"old": "hypnos/consolidation_divergence.json", "new": "sleep/consolidation_divergence.json", "scope": "persisted"},
    {"old": "hypnos/organ_window.json", "new": "sleep/organ_window.json", "scope": "persisted"},
    {"old": "perception/desired.json", "new": "perceptual_locus/desired.json", "scope": "persisted"},
    {"old": "perception/runtime.json", "new": "perceptual_locus/runtime.json", "scope": "persisted"},
    {"old": "praxis/audit.log", "new": "effectors/audit.log", "scope": "persisted"},
    {"old": "praxis/notifications.log", "new": "effectors/notifications.log", "scope": "persisted"},
    {"old": "lifecycle/gestation_readout.json", "new": "lifecycle/development_readout.json", "scope": "persisted"},
    {"old": "lifecycle/birth_request.json", "new": "lifecycle/maturation_request.json", "scope": "persisted"},
    {"old": "lifecycle/birth_ack.json", "new": "lifecycle/maturation_ack.json", "scope": "persisted"},
    {"old": "lifecycle/gestation_progress.json", "new": "lifecycle/development_progress.json", "scope": "persisted"},
    {"old": "lifecycle/gestation_viability.json", "new": "lifecycle/development_viability.json", "scope": "persisted"},
    {"old": "individuation/birth_adapter.gguf", "new": "individuation/maturation_adapter.gguf", "scope": "persisted"},
    {"old": "individuation/birth_pending", "new": "individuation/maturation_pending", "scope": "persisted"},
)

COLLECTIONS = (
    {"old": "mnemos_", "new": "episodic_memory_", "scope": "persisted"},
    {"old": "empatheia_agents", "new": "social_cognition_agents", "scope": "persisted"},
)

STORED_TAGS = (
    {"old": "kaine-phantasia-rssm-npz-v1", "new": "kaine-world-model-rssm-npz-v1", "scope": "persisted"},
    {"old": "phantasia-encoder-v1", "new": "world-model-encoder-v1", "scope": "persisted"},
    {"old": "birth", "new": "maturation", "scope": "persisted"},
    {"old": "failed:gestation_unviable", "new": "failed:development_unviable", "scope": "persisted"},
    # divergence arm name stored in state/preservation/divergence_edge.json
    {"old": "eidolon_drift", "new": "self_model_drift", "scope": "persisted"},
)

STAGE_VALUES = (
    {"old": "gestation", "new": "development", "scope": "persisted"},
)

STAGE_FIELDS = (
    {"old": "gestation_started_at", "new": "development_started_at", "scope": "persisted"},
    {"old": "womb_t_at_birth", "new": "stimulus_source_t_at_maturation", "scope": "persisted"},
    {"old": "womb_seed", "new": "stimulus_source_seed", "scope": "persisted"},
    {"old": "womb_params_digest", "new": "stimulus_source_params_digest", "scope": "persisted"},
    {"old": "birth_bloom_ends_at", "new": "maturation_bloom_ends_at", "scope": "persisted"},
    {"old": "hypnos_cursor", "new": "sleep_cursor", "scope": "persisted"},
)

BUNDLE_MEMBERS = (
    {"old": "gestation/", "new": "development/", "scope": "keys"},
)

LIVED_ARTIFACTS = (
    {"old": "phantasia/world_model.ckpt", "new": "world_model/world_model.ckpt", "scope": "persisted"},
    {"old": "hypnos/consolidation_divergence.json", "new": "sleep/consolidation_divergence.json", "scope": "persisted"},
    {"old": "perception/desired.json", "new": "perceptual_locus/desired.json", "scope": "persisted"},
)

PACKAGING = (
    {"kind": "pip_extra", "old": "nexus", "new": "dashboard", "scope": "operator"},
    {"kind": "entry_point", "old": "kaine.nexus", "new": "kaine.dashboard", "scope": "operator"},
    {"kind": "quadlet_unit", "old": "kaine-nexus.container", "new": "kaine-dashboard.container", "scope": "operator"},
    {"kind": "compose_service", "old": "nexus", "new": "dashboard", "scope": "operator"},
    {"kind": "module_shim", "old": "kaine.lifecycle.mnemos_recover", "new": "kaine.lifecycle.episodic_memory_recover", "scope": "operator"},
    {"kind": "module_shim", "old": "kaine.nexus", "new": "kaine.dashboard", "scope": "operator"},
)

del _MODULE_CLASSES
