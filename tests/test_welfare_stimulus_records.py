# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The per-viewing stimulus-control welfare record and readout.

The effector, the controller and the affect module feed the tally; the welfare
observer writes its record to the welfare log. Content-free: counts, seconds,
shares, gains, declared action names and item identifiers.
"""
from __future__ import annotations

from typing import Any

import pytest

from kaine.modules.effectors.effectors import StimulusRequest
from kaine.modules.effectors.stimulus.config import StimulusControlConfig
from kaine.modules.effectors.stimulus.records import RECORD, StimulusTally
from kaine.modules.effectors.stimulus.runtime import StimulusControlRuntime
from tests.stimulus_media import write_manifest


class _Mono:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def write(self, entry: dict[str, Any]) -> None:
        self.rows.append(entry)


def _runtime(tmp_path, **section):
    pytest.importorskip("av")
    mono = _Mono()
    runtime = StimulusControlRuntime(
        StimulusControlConfig.from_section({"enabled": True, **section}), now=mono, seed=1
    )
    manifest = write_manifest(
        tmp_path / "films",
        [("a.mkv", (255, 0, 0), 300.0, 0.5), ("b.mkv", (0, 255, 0), 400.0, 0.5), ("c.mkv", (0, 0, 255), 500.0, 0.5)],
    )
    clock = runtime.install_programme(str(manifest), probe=lambda item: 1000.0, start=False, monotonic=mono)
    clock.start()
    runtime.controller.poll_once()
    return mono, runtime, clock


def _strings(value, out):
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            out.append(str(k))
            _strings(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _strings(v, out)
    return out


async def test_a_viewing_with_skips_and_a_refused_louder(tmp_path):
    mono, runtime, clock = _runtime(tmp_path, min_interval_s=30.0)
    effector = runtime.effector()
    mono.t = 10.0
    runtime.controller.poll_once()
    assert (await effector.act(StimulusRequest(action="next"))).success
    mono.t = 20.0
    assert not (await effector.act(StimulusRequest(action="louder"))).success  # too soon
    mono.t = 45.0
    runtime.controller.poll_once()
    assert (await effector.act(StimulusRequest(action="next"))).success
    mono.t = 50.0
    runtime.controller.poll_once()
    record = runtime.tally.record()
    assert record["record"] == RECORD
    assert record["commands"]["next"] == 2
    assert sum(record["refused"].values()) == 1 and record["refused"]["louder"] == 1
    # Item identifiers (channel, manifest order) in the order visited.
    assert record["items_visited"] == [[0, 0], [0, 1], [0, 2]]
    assert record["awake_s"] == pytest.approx(50.0)
    assert record["acts_per_awake_hour"] == pytest.approx(2 / (50.0 / 3600.0))
    assert record["entity_paused_share"] == 0.0
    assert record["gain_seconds"] == {"+0.0": pytest.approx(50.0)}


async def test_paused_share_and_gain_distribution_are_time_weighted(tmp_path):
    mono, runtime, clock = _runtime(tmp_path, min_interval_s=1.0, pause_max_s=40.0)
    effector = runtime.effector()
    mono.t = 10.0
    runtime.controller.poll_once()
    await effector.act(StimulusRequest(action="louder"))
    mono.t = 20.0
    runtime.controller.poll_once()
    await effector.act(StimulusRequest(action="pause"))
    mono.t = 30.0
    runtime.controller.poll_once()
    mono.t = 60.0  # the pause releases itself at 40 s of entity time (20 + 40)
    runtime.controller.poll_once()
    mono.t = 80.0
    runtime.controller.poll_once()
    record = runtime.tally.record()
    assert record["auto_releases"] == 1
    # Held from 20 s to the poll at 60 s that released it: 40 of 80 awake seconds.
    assert record["entity_paused_share"] == pytest.approx(40.0 / 80.0)
    assert record["gain_seconds"] == {"+0.0": pytest.approx(10.0), "+2.0": pytest.approx(70.0)}
    assert record["gain_mean_db"] == pytest.approx(2.0 * 70.0 / 80.0)


async def test_sleep_and_freeze_are_not_awake_time(tmp_path):
    mono, runtime, clock = _runtime(tmp_path)
    mono.t = 10.0
    runtime.controller.poll_once()
    clock.pause("sleep")
    mono.t = 100.0
    runtime.controller.poll_once()
    clock.resume("sleep")
    clock.pause("freeze")
    mono.t = 130.0
    runtime.controller.poll_once()
    clock.resume("freeze")
    mono.t = 140.0
    runtime.controller.poll_once()
    assert runtime.tally.record()["awake_s"] == pytest.approx(20.0)


def test_readout_splits_after_own_act_from_the_rest():
    tally = StimulusTally(StimulusControlConfig.from_section({"enabled": True}))
    # 20 s outside any window, bored, no novelty.
    for _ in range(20):
        tally.observe_affect(1.0, awake=True, in_window=False, boredom=0.8, boredom_above=True,
                             alert_excess=0.0, learning_progress=0.0)
    # An act's window: 10 s of novelty in which boredom falls below its bar.
    for k in range(10):
        tally.observe_affect(1.0, awake=True, in_window=True, boredom=0.8 - 0.02 * k,
                             boredom_above=k < 5, alert_excess=0.6, learning_progress=0.1)
    tally.observe_affect(1.0, awake=True, in_window=False, boredom=0.6, boredom_above=False,
                         alert_excess=0.0, learning_progress=0.0)
    readout = tally.record()["readout"]
    after, rest = readout["after_own_act"], readout["otherwise"]
    assert after["seconds"] == pytest.approx(10.0)
    assert after["boredom_above_share"] == pytest.approx(0.5)
    assert after["mean_alert_excess"] == pytest.approx(0.6)
    assert after["mean_learning_progress"] == pytest.approx(0.1)
    assert rest["seconds"] == pytest.approx(21.0)
    assert rest["boredom_above_share"] == pytest.approx(20.0 / 21.0)
    assert rest["mean_alert_excess"] == pytest.approx(0.0)
    assert readout["acts_observed"] == 1 and readout["acts_with_boredom_fall"] == 1


def test_asleep_samples_are_left_out_of_the_readout():
    tally = StimulusTally(StimulusControlConfig.from_section({"enabled": True}))
    tally.observe_affect(5.0, awake=False, in_window=False, boredom=0.9, boredom_above=True,
                         alert_excess=0.0, learning_progress=0.0)
    assert tally.record()["readout"]["otherwise"]["seconds"] == 0.0


async def test_the_welfare_observer_writes_the_record_content_free(tmp_path):
    from kaine.evaluation.observers.welfare_observer import WelfareObserver

    mono, runtime, clock = _runtime(tmp_path, min_interval_s=1.0)
    effector = runtime.effector()
    mono.t = 5.0
    runtime.controller.poll_once()
    await effector.act(StimulusRequest(action="next"))
    await effector.act(StimulusRequest(action="next"))  # too soon: refused
    sink = _Sink()
    observer = WelfareObserver(object(), sink, supplementary_records=runtime.tally.take_records)
    await observer._write_supplementary_records()
    await observer._write_supplementary_records()  # unchanged: nothing more is written
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row["record"] == RECORD and "ts" in row
    declared = set(runtime.config.declared_actions()) | {"other"}
    fixed = {
        "ts", "record", "stage", "commands", "refused", "auto_releases", "awake_s",
        "acts_per_awake_hour", "entity_paused_share", "gain_seconds", "gain_mean_db",
        "items_visited", "items_visited_dropped", "readout", "after_own_act", "otherwise",
        "acts_observed", "acts_with_boredom_fall", "seconds", "boredom_above_share",
        "mean_alert_excess", "mean_learning_progress", RECORD, "minimal",
    }
    strings = set(_strings({k: v for k, v in row.items() if k != "ts"}, []))
    strings.discard(row["ts"])
    gain_keys = set(row["gain_seconds"])
    assert strings <= fixed | declared | gain_keys, strings - fixed - declared - gain_keys


async def test_no_provider_writes_nothing_extra():
    from kaine.evaluation.observers.welfare_observer import WelfareObserver

    sink = _Sink()
    observer = WelfareObserver(object(), sink)
    await observer._write_supplementary_records()
    assert sink.rows == []
