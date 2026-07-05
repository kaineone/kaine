# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class MetricsReader(Protocol):
    async def initialize(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def read_metrics(self) -> dict[str, float]: ...

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None: ...


class SystemMetricsReader:
    """Default MetricsReader using psutil and pynvml.

    Every external call is wrapped to tolerate the most common failures:
    a host without NVIDIA drivers, a container with restricted
    /proc/diskstats, or a kernel that hides specific psutil counters.
    Each failure produces a missing key in the metrics dict rather than
    an exception; the wellness calculator handles missing keys by
    redistributing weight onto the metrics that are present.
    """

    def __init__(
        self,
        *,
        cycle_latency_window: int = 64,
    ) -> None:
        if cycle_latency_window <= 0:
            raise ValueError("cycle_latency_window must be positive")
        self._latency_samples: deque[float] = deque(maxlen=cycle_latency_window)
        self._gpu_available = False
        self._nvml: Any = None
        self._boot_time: float | None = None

    async def initialize(self) -> None:
        try:
            import pynvml  # type: ignore[import-untyped]

            await asyncio.to_thread(pynvml.nvmlInit)
            self._nvml = pynvml
            self._gpu_available = True
            log.info("pynvml initialized; GPU metrics enabled")
        except Exception as exc:
            log.warning(
                "pynvml init failed: %s; GPU metrics disabled for this run", exc
            )
            self._nvml = None
            self._gpu_available = False
        try:
            import psutil  # type: ignore[import-untyped]

            self._boot_time = await asyncio.to_thread(psutil.boot_time)
        except Exception as exc:
            log.warning("psutil.boot_time failed: %s; uptime disabled", exc)
            self._boot_time = None

    async def shutdown(self) -> None:
        if self._gpu_available and self._nvml is not None:
            try:
                await asyncio.to_thread(self._nvml.nvmlShutdown)
            except Exception:
                log.warning("pynvml shutdown failed", exc_info=True)

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        self._latency_samples.append(float(wall_duration_ms))

    async def read_metrics(self) -> dict[str, float]:
        return await asyncio.to_thread(self._read_metrics_sync)

    def _read_metrics_sync(self) -> dict[str, float]:
        import time

        import psutil  # type: ignore[import-untyped]

        metrics: dict[str, float] = {}

        try:
            metrics["cpu_percent"] = float(psutil.cpu_percent(interval=None))
        except Exception:
            log.warning("psutil.cpu_percent failed", exc_info=True)

        try:
            metrics["ram_percent"] = float(psutil.virtual_memory().percent)
        except Exception:
            log.warning("psutil.virtual_memory failed", exc_info=True)

        try:
            io = psutil.disk_io_counters()
            if io is not None:
                metrics["disk_read_bytes"] = float(io.read_bytes)
                metrics["disk_write_bytes"] = float(io.write_bytes)
        except Exception:
            log.debug("psutil.disk_io_counters unavailable", exc_info=True)

        if self._gpu_available and self._nvml is not None:
            try:
                count = self._nvml.nvmlDeviceGetCount()
                for i in range(int(count)):
                    handle = self._nvml.nvmlDeviceGetHandleByIndex(i)
                    try:
                        temp = self._nvml.nvmlDeviceGetTemperature(
                            handle, self._nvml.NVML_TEMPERATURE_GPU
                        )
                        metrics[f"gpu_{i}_temp_c"] = float(temp)
                    except Exception:
                        log.debug("gpu %d temp read failed", i, exc_info=True)
                    try:
                        mem = self._nvml.nvmlDeviceGetMemoryInfo(handle)
                        if mem.total > 0:
                            metrics[f"gpu_{i}_vram_percent"] = float(
                                mem.used / mem.total * 100
                            )
                    except Exception:
                        log.debug("gpu %d mem read failed", i, exc_info=True)
            except Exception:
                log.warning("pynvml device enumeration failed", exc_info=True)

        if self._latency_samples:
            metrics["cycle_latency_avg_ms"] = float(
                sum(self._latency_samples) / len(self._latency_samples)
            )

        if self._boot_time is not None:
            metrics["uptime_s"] = float(time.time() - self._boot_time)

        return metrics
