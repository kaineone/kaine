# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Thread-safety regression test for MaternalVoiceLayer.plan_for."""

import threading
import time
from collections import defaultdict

import numpy as np

from kaine.modules.audition.maternal_voice import (
    MaternalVoiceLayer,
    MaternalVoiceParams,
    MaternalVoiceRepertoire,
)
from kaine.modules.stimulus_source_signal import StimulusSourceParams


def test_plan_for_caches_each_slot_once():
    sample_rate = 16000
    t = np.arange(2000, dtype=np.float64) / sample_rate
    sine = np.sin(2.0 * np.pi * 440.0 * t).astype(np.float64)
    takes = ((sine, sine), (sine, sine), (sine, sine))

    repertoire = MaternalVoiceRepertoire(
        takes=takes,
        item_ids=("a", "b", "c"),
        initial_unlocked=1,
        sample_rate=sample_rate,
        manifest_sha256="0" * 64,
    )

    params = MaternalVoiceParams(episode_probability=1.0, slot_seconds=5.0)
    layer = MaternalVoiceLayer(
        repertoire=repertoire,
        params=params,
        seed=3,
        stimulus_params=StimulusSourceParams(),
        background_rms=1.0,
    )

    original_slot_plan = layer.slot_plan
    call_counts = defaultdict(int)

    def counting_slot_plan(slot: int, unlocked: int):
        call_counts[slot] += 1
        time.sleep(0.001)
        return original_slot_plan(slot, unlocked)

    layer.slot_plan = counting_slot_plan

    n_threads = 8
    n_slots = 200
    thread_results = [None] * n_threads
    errors = []
    errors_lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker(index: int) -> None:
        try:
            local = {}
            awake_seconds = index * 10_000.0
            for slot in range(n_slots):
                local[slot] = layer.plan_for(slot, awake_seconds)
                barrier.wait()
            thread_results[index] = local
        except Exception as exc:
            with errors_lock:
                errors.append((index, exc))

    threads = [
        threading.Thread(target=worker, args=(i,), name=f"plan-worker-{i}")
        for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"worker exceptions: {errors}"

    for slot in range(n_slots):
        count = call_counts[slot]
        assert count == 1, f"slot {slot} was planned {count} times"

    for slot in range(n_slots):
        plans = [thread_results[i][slot] for i in range(n_threads)]
        reference = plans[0]
        for i, plan in enumerate(plans[1:], start=1):
            assert plan == reference, f"slot {slot} plan differs in thread {i}"

    # The final slots are still cached, so a later call returns the same tuple.
    for slot in (n_slots - 3, n_slots - 2, n_slots - 1):
        assert layer.plan_for(slot, 0.0) == thread_results[0][slot]
