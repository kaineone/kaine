# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json


from kaine import perception_state


def test_default_state_empty(tmp_path):
    runtime = perception_state.read_runtime(tmp_path / "runtime.json")
    assert runtime.audio_live_active is False
    assert runtime.video_live_active is False
    assert runtime.audio_last_started_at is None


def test_default_desired_empty(tmp_path):
    desired = perception_state.read_desired(tmp_path / "desired.json")
    assert desired.audio_live_desired is False
    assert desired.video_live_desired is False


def test_update_audio_runtime_records_started_at(tmp_path):
    path = tmp_path / "runtime.json"
    after = perception_state.update_audio_runtime(True, path)
    assert after.audio_live_active is True
    assert after.audio_last_started_at is not None
    raw = json.loads(path.read_text())
    assert raw["audio_live_active"] is True


def test_update_audio_runtime_records_stopped_at(tmp_path):
    path = tmp_path / "runtime.json"
    perception_state.update_audio_runtime(True, path)
    after = perception_state.update_audio_runtime(False, path)
    assert after.audio_live_active is False
    assert after.audio_last_stopped_at is not None


def test_update_video_runtime_independent_of_audio(tmp_path):
    path = tmp_path / "runtime.json"
    perception_state.update_audio_runtime(True, path)
    perception_state.update_video_runtime(True, path)
    cur = perception_state.read_runtime(path)
    assert cur.audio_live_active is True
    assert cur.video_live_active is True


def test_desired_audio_toggle(tmp_path):
    path = tmp_path / "desired.json"
    after = perception_state.write_desired_audio(True, path)
    assert after.audio_live_desired is True
    after = perception_state.write_desired_audio(False, path)
    assert after.audio_live_desired is False


def test_atomic_write_leaves_no_tmp_file(tmp_path):
    path = tmp_path / "runtime.json"
    perception_state.update_audio_runtime(True, path)
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []


def test_runtime_file_contains_only_operational_keys(tmp_path):
    path = tmp_path / "runtime.json"
    perception_state.update_audio_runtime(True, path)
    perception_state.update_video_runtime(True, path)
    raw = json.loads(path.read_text())
    # Allowed keys only — never any sensory content.
    allowed = {
        "audio_live_active",
        "video_live_active",
        "audio_last_started_at",
        "video_last_started_at",
        "audio_last_stopped_at",
        "video_last_stopped_at",
    }
    assert set(raw.keys()) <= allowed
