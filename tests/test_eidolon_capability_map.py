# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for CapabilityMapBuilder (eidolon-self-inference change).

Coverage (task 6.2):
- Whitelist entries appear in capability_map.
- EFE outcomes (Nous policy events) are recorded.
- Empty state produces empty map.
"""
from __future__ import annotations


from kaine.modules.eidolon.capability_map import CapabilityMapBuilder


def test_empty_builder_produces_empty_map():
    """With no whitelist and no policy events, build() returns {}."""
    builder = CapabilityMapBuilder()
    assert builder.build() == {}


def test_whitelist_entries_appear_in_capability_map():
    """Praxis whitelist commands are included under 'effectors'."""
    builder = CapabilityMapBuilder(whitelist_commands=["echo", "ls"])
    cap = builder.build()
    assert "effectors" in cap
    assert sorted(cap["effectors"]) == ["echo", "ls"]


def test_whitelist_entries_sorted():
    """Effectors are returned in sorted order regardless of insertion order."""
    builder = CapabilityMapBuilder(whitelist_commands=["zz", "aa", "mm"])
    cap = builder.build()
    assert cap["effectors"] == sorted(cap["effectors"])


def test_efe_outcomes_recorded():
    """Nous policy events accumulate in policy_outcomes."""
    builder = CapabilityMapBuilder()
    builder.observe_policy({"policy": "request_think", "expected_free_energy": -0.4})
    builder.observe_policy({"policy": "request_think", "expected_free_energy": -0.6})
    builder.observe_policy({"policy": "no_op", "expected_free_energy": 0.0})

    cap = builder.build()
    assert "policy_outcomes" in cap
    outcomes = cap["policy_outcomes"]
    assert outcomes["request_think"]["count"] == 2
    assert abs(outcomes["request_think"]["mean_efe"] - (-0.5)) < 1e-4
    assert outcomes["no_op"]["count"] == 1


def test_empty_policy_label_ignored():
    """Events with missing or empty policy labels are silently dropped."""
    builder = CapabilityMapBuilder()
    builder.observe_policy({"policy": "", "expected_free_energy": 0.0})
    builder.observe_policy({"expected_free_energy": 0.0})
    cap = builder.build()
    assert "policy_outcomes" not in cap


def test_whitelist_and_outcomes_combined():
    """Both effectors and policy_outcomes appear together when both are present."""
    builder = CapabilityMapBuilder(whitelist_commands=["echo"])
    builder.observe_policy({"policy": "request_speak", "expected_free_energy": -0.3})

    cap = builder.build()
    assert "effectors" in cap
    assert "policy_outcomes" in cap
    assert "echo" in cap["effectors"]
    assert "request_speak" in cap["policy_outcomes"]


def test_capability_map_no_raw_text():
    """capability_map must never contain raw string content from payloads."""
    secret = "secret_raw_content_xyz"
    builder = CapabilityMapBuilder(whitelist_commands=["cmd"])
    # Include secret in a payload field that should never be stored.
    builder.observe_policy(
        {"policy": "request_think", "expected_free_energy": -0.5, "text": secret}
    )
    cap = builder.build()
    cap_str = str(cap)
    assert secret not in cap_str, "raw payload content leaked into capability_map"
