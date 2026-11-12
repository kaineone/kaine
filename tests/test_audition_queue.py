# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from kaine.modules.audition.audio_queue import BoundedAudioQueue, QueuedSegment


def test_enqueue_and_drain_basic():
    q = BoundedAudioQueue()
    for i in range(3):
        assert q.enqueue(b"\x00", 16000, f"s{i}") is True
    assert q.pending == 3
    segs = q.drain()
    assert len(segs) == 3
    assert [s.source_label for s in segs] == ["s0", "s1", "s2"]
    assert q.pending == 0


def test_count_limit_drops_oldest():
    q = BoundedAudioQueue(max_count=2)
    q.enqueue(b"a", 16000, "s0")
    q.enqueue(b"b", 16000, "s1")
    q.enqueue(b"c", 16000, "s2")
    assert q.total_drops == 1
    segs = q.drain()
    assert len(segs) == 2
    assert [s.source_label for s in segs] == ["s1", "s2"]


def test_age_limit_evicts_stale():
    q = BoundedAudioQueue(max_age_s=0.1)
    q.enqueue(b"a", 16000, "first")
    time.sleep(0.15)
    q.enqueue(b"b", 16000, "second")
    assert q.total_drops == 1
    segs = q.drain()
    assert len(segs) == 1
    assert segs[0].source_label == "second"


def test_drain_evicts_stale():
    q = BoundedAudioQueue(max_age_s=0.1)
    q.enqueue(b"a", 16000, "s0")
    q.enqueue(b"b", 16000, "s1")
    time.sleep(0.15)
    segs = q.drain()
    assert segs == []
    assert q.total_drops == 2


def test_clear_does_not_count_as_drop():
    q = BoundedAudioQueue()
    q.enqueue(b"a", 16000, "s0")
    q.enqueue(b"b", 16000, "s1")
    q.clear()
    assert q.total_drops == 0
    assert q.pending == 0


def test_empty_drain():
    q = BoundedAudioQueue()
    assert q.drain() == []


def test_thread_safety():
    q = BoundedAudioQueue(max_count=50)

    def worker():
        for _ in range(100):
            q.enqueue(b"x", 16000, "t")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert q.total_drops + q.pending == 400


def test_no_disk_io():
    with patch("builtins.open", side_effect=IOError("no disk")):
        q = BoundedAudioQueue()
        assert q.enqueue(b"x", 16000, "s") is True
        segs = q.drain()
        assert len(segs) == 1


def test_queue_drop_event_fired():
    with patch("kaine.residency.events.record_queue_drop") as mock_record:
        q = BoundedAudioQueue(max_count=1)
        q.enqueue(b"a", 16000, "s0")
        q.enqueue(b"b", 16000, "s1")
        assert mock_record.called
        assert mock_record.call_args_list[0].kwargs["name"] == "perception_queue"


def test_queued_segment_is_frozen():
    seg = QueuedSegment(b"x", 16000, "mic", time.monotonic())
    with pytest.raises(AttributeError):
        seg.source_label = "changed"  # type: ignore[misc]


def test_invalid_bounds():
    with pytest.raises(ValueError):
        BoundedAudioQueue(max_count=0)
    with pytest.raises(ValueError):
        BoundedAudioQueue(max_age_s=-1.0)


def test_item_provenance_preserved():
    q = BoundedAudioQueue()
    q.enqueue(b"x", 16000, "mic", item={"idx": 5})
    segs = q.drain()
    assert segs[0].item == {"idx": 5}
