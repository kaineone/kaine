# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Generated reference data for PyTorch wheel indexes.

DATA_DATE = "2026-09-22"

Sources:
  - download.pytorch.org simple indexes
  - PEP 658 wheel METADATA sidecar files
  - PyTorch release-tag build configs (``.ci/manywheel/build_cuda.sh``,
    ``.ci/manywheel/build_env_setup.py``, ``.ci/docker/manywheel/build.sh``)

Run ``python -m kaine.wheel_index --verify-indexes`` to compare this data
against the live indexes and report drift.
"""

from __future__ import annotations

DATA_DATE: str = "2026-09-22"

PUBLISHED: dict[str, dict[str, tuple[str, ...]]] = {
    "cpu": {
        "x86_64": (
            "2.14.0", "2.13.0", "2.12.1", "2.12.0", "2.11.0", "2.10.0", "2.9.1"
        ),
        "aarch64": (
            "2.14.0", "2.13.0", "2.12.1", "2.12.0", "2.11.0", "2.10.0", "2.9.1"
        ),
    },
    "cu126": {
        "x86_64": (
            "2.14.0", "2.13.0", "2.12.1", "2.12.0", "2.11.0", "2.10.0", "2.9.1"
        ),
        "aarch64": (
            "2.14.0", "2.13.0", "2.12.1", "2.12.0", "2.11.0", "2.10.0", "2.9.1"
        ),
    },
    "cu128": {
        "x86_64": ("2.11.0", "2.10.0", "2.9.1"),
        "aarch64": ("2.11.0", "2.10.0", "2.9.1"),
    },
    "cu129": {
        "x86_64": ("2.13.0", "2.12.1", "2.11.0", "2.10.0", "2.9.1"),
        "aarch64": ("2.13.0", "2.12.1", "2.11.0", "2.10.0", "2.9.1"),
    },
    "cu130": {
        "x86_64": (
            "2.14.0", "2.13.0", "2.12.1", "2.12.0", "2.11.0", "2.10.0", "2.9.1"
        ),
        "aarch64": (
            "2.14.0", "2.13.0", "2.12.1", "2.12.0", "2.11.0", "2.10.0", "2.9.1"
        ),
    },
    "cu132": {
        "x86_64": ("2.14.0", "2.13.0", "2.12.1", "2.12.0"),
        "aarch64": ("2.14.0", "2.13.0", "2.12.1", "2.12.0"),
    },
    "rocm6.3": {"x86_64": ("2.9.1",)},
    "rocm6.4": {"x86_64": ("2.9.1",)},
    "rocm7.0": {"x86_64": ("2.10.0",)},
    "rocm7.1": {"x86_64": ("2.13.0", "2.12.1", "2.12.0", "2.11.0", "2.10.0")},
    "rocm7.2": {"x86_64": ("2.14.0", "2.13.0", "2.12.1", "2.12.0", "2.11.0")},
    "xpu": {
        "x86_64": (
            "2.14.0", "2.13.0", "2.12.1", "2.12.0", "2.11.0", "2.10.0", "2.9.1"
        ),
    },
}

_CPU_LIKE_COMPANIONS: dict[str, dict[str, str | None]] = {
    "2.14.0": {"torchvision": "0.29.0", "torchaudio": "2.11.0"},
    "2.13.0": {"torchvision": "0.28.0", "torchaudio": "2.11.0"},
    "2.12.1": {"torchvision": "0.27.1", "torchaudio": "2.11.0"},
    "2.12.0": {"torchvision": "0.27.0", "torchaudio": "2.11.0"},
    "2.11.0": {"torchvision": "0.26.0", "torchaudio": "2.11.0"},
    "2.10.0": {"torchvision": "0.25.0", "torchaudio": "2.10.0"},
    "2.9.1": {"torchvision": "0.24.1", "torchaudio": "2.9.1"},
}

_CU128_COMPANIONS: dict[str, dict[str, str | None]] = {
    "2.11.0": {"torchvision": "0.26.0", "torchaudio": "2.11.0"},
    "2.10.0": {"torchvision": "0.25.0", "torchaudio": "2.10.0"},
    "2.9.1": {"torchvision": "0.24.1", "torchaudio": "2.9.1"},
}

_CU129_COMPANIONS: dict[str, dict[str, str | None]] = {
    "2.13.0": {"torchvision": "0.28.0", "torchaudio": "2.11.0"},
    "2.12.1": {"torchvision": "0.27.1", "torchaudio": "2.11.0"},
    "2.11.0": {"torchvision": "0.26.0", "torchaudio": "2.11.0"},
    "2.10.0": {"torchvision": "0.25.0", "torchaudio": "2.10.0"},
    "2.9.1": {"torchvision": "0.24.1", "torchaudio": "2.9.1"},
}

_CU132_COMPANIONS: dict[str, dict[str, str | None]] = {
    "2.14.0": {"torchvision": "0.29.0", "torchaudio": None},
    "2.13.0": {"torchvision": "0.28.0", "torchaudio": None},
    "2.12.1": {"torchvision": "0.27.1", "torchaudio": None},
    "2.12.0": {"torchvision": "0.27.0", "torchaudio": None},
}

_ROCM71_COMPANIONS: dict[str, dict[str, str | None]] = {
    "2.13.0": {"torchvision": "0.28.0", "torchaudio": "2.11.0"},
    "2.12.1": {"torchvision": "0.27.1", "torchaudio": "2.11.0"},
    "2.12.0": {"torchvision": "0.27.0", "torchaudio": "2.11.0"},
    "2.11.0": {"torchvision": "0.26.0", "torchaudio": "2.11.0"},
    "2.10.0": {"torchvision": "0.25.0", "torchaudio": "2.10.0"},
}

_ROCM72_COMPANIONS: dict[str, dict[str, str | None]] = {
    "2.14.0": {"torchvision": "0.29.0", "torchaudio": "2.11.0"},
    "2.13.0": {"torchvision": "0.28.0", "torchaudio": "2.11.0"},
    "2.12.1": {"torchvision": "0.27.1", "torchaudio": "2.11.0"},
    "2.12.0": {"torchvision": "0.27.0", "torchaudio": "2.11.0"},
    "2.11.0": {"torchvision": "0.26.0", "torchaudio": "2.11.0"},
}

COMPANIONS: dict[str, dict[str, dict[str, dict[str, str | None]]]] = {
    "cpu": {
        "x86_64": _CPU_LIKE_COMPANIONS,
        "aarch64": dict(_CPU_LIKE_COMPANIONS),
    },
    "cu126": {
        "x86_64": _CPU_LIKE_COMPANIONS,
        "aarch64": dict(_CPU_LIKE_COMPANIONS),
    },
    "cu128": {
        "x86_64": _CU128_COMPANIONS,
        "aarch64": dict(_CU128_COMPANIONS),
    },
    "cu129": {
        "x86_64": _CU129_COMPANIONS,
        "aarch64": dict(_CU129_COMPANIONS),
    },
    "cu130": {
        "x86_64": _CPU_LIKE_COMPANIONS,
        "aarch64": dict(_CPU_LIKE_COMPANIONS),
    },
    "cu132": {
        "x86_64": _CU132_COMPANIONS,
        "aarch64": dict(_CU132_COMPANIONS),
    },
    "rocm6.3": {
        "x86_64": {"2.9.1": {"torchvision": "0.24.1", "torchaudio": "2.9.1"}},
    },
    "rocm6.4": {
        "x86_64": {"2.9.1": {"torchvision": "0.24.1", "torchaudio": "2.9.1"}},
    },
    "rocm7.0": {
        "x86_64": {"2.10.0": {"torchvision": "0.25.0", "torchaudio": "2.10.0"}},
    },
    "rocm7.1": {
        "x86_64": _ROCM71_COMPANIONS,
    },
    "rocm7.2": {
        "x86_64": _ROCM72_COMPANIONS,
    },
    "xpu": {
        "x86_64": _CPU_LIKE_COMPANIONS,
    },
}

CUDA_ARCH: dict[str, dict[str, dict[str, str]]] = {
    "2.9.1": {
        "cu126": {
            "x86_64": "5.0;6.0;7.0;7.5;8.0;8.6;9.0",
            "aarch64": "5.0;6.0;7.0;7.5;8.0;8.6;9.0",
        },
        "cu128": {
            "x86_64": "7.0;7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "7.0;7.5;8.0;8.6;9.0;10.0;12.0",
        },
        "cu129": {
            "x86_64": "7.0;7.5;8.0;8.6;9.0;10.0;12.0+PTX",
            "aarch64": "7.0;7.5;8.0;8.6;9.0;10.0;12.0+PTX",
        },
        "cu130": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0+PTX",
            "aarch64": "7.5;8.0;8.6;9.0;10.0;12.0+PTX",
        },
    },
    "2.10.0": {
        "cu126": {
            "x86_64": "5.0;6.0;7.0;7.5;8.0;8.6;9.0",
            "aarch64": "8.0;9.0",
        },
        "cu128": {
            "x86_64": "7.0;7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;12.0",
        },
        "cu129": {
            "x86_64": "7.0;7.5;8.0;8.6;9.0;10.0;12.0+PTX",
            "aarch64": "8.0;9.0;10.0;12.0+PTX",
        },
        "cu130": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0+PTX",
            "aarch64": "8.0;9.0;10.0;11.0;12.0+PTX",
        },
    },
    "2.11.0": {
        "cu126": {
            "x86_64": "5.0;6.0;7.0;7.5;8.0;8.6;9.0",
            "aarch64": "8.0;9.0",
        },
        "cu128": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;12.0",
        },
        "cu129": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0+PTX",
            "aarch64": "8.0;9.0;10.0;12.0+PTX",
        },
        "cu130": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;11.0;12.0",
        },
    },
    "2.12.0": {
        "cu126": {
            "x86_64": "5.0;6.0;7.0;7.5;8.0;8.6;9.0",
            "aarch64": "8.0;9.0",
        },
        "cu128": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;12.0",
        },
        "cu129": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;12.0",
        },
        "cu130": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;11.0;12.0",
        },
        "cu132": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;11.0;12.0",
        },
    },
    "2.12.1": {
        "cu126": {
            "x86_64": "5.0;6.0;7.0;7.5;8.0;8.6;9.0",
            "aarch64": "8.0;9.0",
        },
        "cu128": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;12.0",
        },
        "cu129": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;12.0",
        },
        "cu130": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;11.0;12.0",
        },
        "cu132": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;11.0;12.0",
        },
    },
    "2.13.0": {
        "cu126": {
            "x86_64": "5.0;6.0;7.0;7.5;8.0;8.6;9.0",
            "aarch64": "8.0;9.0",
        },
        "cu129": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;12.0",
        },
        "cu130": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;11.0;12.0",
        },
        "cu132": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;11.0;12.0",
        },
    },
    "2.14.0": {
        "cu126": {
            "x86_64": "5.0;6.0;7.0;7.5;8.0;8.6;9.0",
            "aarch64": "8.0;9.0",
        },
        "cu130": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;11.0;12.0",
        },
        "cu132": {
            "x86_64": "7.5;8.0;8.6;9.0;10.0;12.0",
            "aarch64": "8.0;9.0;10.0;11.0;12.0",
        },
    },
}

CUDA_ARCH_SOURCES: dict[str, dict[str, str]] = {
    "2.9.1": {
        "cu126": "https://raw.githubusercontent.com/pytorch/pytorch/v2.9.1/.ci/manywheel/build_cuda.sh",
        "cu128": "https://raw.githubusercontent.com/pytorch/pytorch/v2.9.1/.ci/manywheel/build_cuda.sh",
        "cu129": "https://raw.githubusercontent.com/pytorch/pytorch/v2.9.1/.ci/manywheel/build_cuda.sh",
        "cu130": "https://raw.githubusercontent.com/pytorch/pytorch/v2.9.1/.ci/manywheel/build_cuda.sh",
    },
    "2.10.0": {
        "cu126": "https://raw.githubusercontent.com/pytorch/pytorch/v2.10.0/.ci/manywheel/build_cuda.sh",
        "cu128": "https://raw.githubusercontent.com/pytorch/pytorch/v2.10.0/.ci/manywheel/build_cuda.sh",
        "cu129": "https://raw.githubusercontent.com/pytorch/pytorch/v2.10.0/.ci/manywheel/build_cuda.sh",
        "cu130": "https://raw.githubusercontent.com/pytorch/pytorch/v2.10.0/.ci/manywheel/build_cuda.sh",
    },
    "2.11.0": {
        "cu126": "https://raw.githubusercontent.com/pytorch/pytorch/v2.11.0/.ci/manywheel/build_cuda.sh",
        "cu128": "https://raw.githubusercontent.com/pytorch/pytorch/v2.11.0/.ci/manywheel/build_cuda.sh",
        "cu129": "https://raw.githubusercontent.com/pytorch/pytorch/v2.11.0/.ci/manywheel/build_cuda.sh",
        "cu130": "https://raw.githubusercontent.com/pytorch/pytorch/v2.11.0/.ci/manywheel/build_cuda.sh",
    },
    "2.12.0": {
        "cu126": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.0/.ci/manywheel/build_cuda.sh",
        "cu128": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.0/.ci/manywheel/build_cuda.sh",
        "cu129": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.0/.ci/manywheel/build_cuda.sh",
        "cu130": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.0/.ci/manywheel/build_cuda.sh",
        "cu132": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.0/.ci/manywheel/build_cuda.sh",
    },
    "2.12.1": {
        "cu126": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.1/.ci/manywheel/build_cuda.sh",
        "cu128": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.1/.ci/manywheel/build_cuda.sh",
        "cu129": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.1/.ci/manywheel/build_cuda.sh",
        "cu130": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.1/.ci/manywheel/build_cuda.sh",
        "cu132": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.1/.ci/manywheel/build_cuda.sh",
    },
    "2.13.0": {
        "cu126": "https://raw.githubusercontent.com/pytorch/pytorch/v2.13.0/.ci/manywheel/build_env_setup.py",
        "cu129": "https://raw.githubusercontent.com/pytorch/pytorch/v2.13.0/.ci/manywheel/build_env_setup.py",
        "cu130": "https://raw.githubusercontent.com/pytorch/pytorch/v2.13.0/.ci/manywheel/build_env_setup.py",
        "cu132": "https://raw.githubusercontent.com/pytorch/pytorch/v2.13.0/.ci/manywheel/build_env_setup.py",
    },
    "2.14.0": {
        "cu126": "https://raw.githubusercontent.com/pytorch/pytorch/v2.14.0/.ci/manywheel/build_env_setup.py",
        "cu130": "https://raw.githubusercontent.com/pytorch/pytorch/v2.14.0/.ci/manywheel/build_env_setup.py",
        "cu132": "https://raw.githubusercontent.com/pytorch/pytorch/v2.14.0/.ci/manywheel/build_env_setup.py",
    },
}

ROCM_ARCH: dict[str, dict] = {
    "2.9.1": {
        "indexes": ("rocm6.3", "rocm6.4"),
        "gfx": (
            "gfx900", "gfx906", "gfx908", "gfx90a", "gfx942",
            "gfx1030", "gfx1100", "gfx1101", "gfx1102",
            "gfx1200", "gfx1201",
        ),
        "source": "https://raw.githubusercontent.com/pytorch/pytorch/v2.9.1/.ci/docker/manywheel/build.sh",
    },
    "2.10.0": {
        "indexes": ("rocm7.0", "rocm7.1"),
        "gfx": (
            "gfx900", "gfx906", "gfx908", "gfx90a", "gfx942",
            "gfx1030", "gfx1100", "gfx1101", "gfx1102",
            "gfx1200", "gfx1201", "gfx950", "gfx1150", "gfx1151",
        ),
        "source": "https://raw.githubusercontent.com/pytorch/pytorch/v2.10.0/.ci/docker/manywheel/build.sh",
    },
    "2.11.0": {
        "indexes": ("rocm7.1", "rocm7.2"),
        "gfx": (
            "gfx900", "gfx906", "gfx908", "gfx90a", "gfx942",
            "gfx1030", "gfx1100", "gfx1101", "gfx1102",
            "gfx1200", "gfx1201", "gfx950", "gfx1150", "gfx1151",
        ),
        "source": "https://raw.githubusercontent.com/pytorch/pytorch/v2.11.0/.ci/docker/manywheel/build.sh",
    },
    "2.12.0": {
        "indexes": ("rocm7.1", "rocm7.2"),
        "gfx": (
            "gfx900", "gfx906", "gfx908", "gfx90a", "gfx942",
            "gfx1030", "gfx1100", "gfx1101", "gfx1102",
            "gfx1200", "gfx1201", "gfx950", "gfx1150", "gfx1151",
        ),
        "source": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.0/.ci/docker/manywheel/build.sh",
    },
    "2.12.1": {
        "indexes": ("rocm7.1", "rocm7.2"),
        "gfx": (
            "gfx900", "gfx906", "gfx908", "gfx90a", "gfx942",
            "gfx1030", "gfx1100", "gfx1101", "gfx1102",
            "gfx1200", "gfx1201", "gfx950", "gfx1150", "gfx1151",
        ),
        "source": "https://raw.githubusercontent.com/pytorch/pytorch/v2.12.1/.ci/docker/manywheel/build.sh",
    },
    "2.13.0": {
        "indexes": ("rocm7.1", "rocm7.2"),
        "gfx": (
            "gfx900", "gfx906", "gfx908", "gfx90a", "gfx942",
            "gfx1030", "gfx1100", "gfx1101", "gfx1102", "gfx1103",
            "gfx1200", "gfx1201", "gfx950", "gfx1150", "gfx1151",
        ),
        "source": "https://raw.githubusercontent.com/pytorch/pytorch/v2.13.0/.ci/docker/manywheel/build.sh",
    },
    "2.14.0": {
        "indexes": ("rocm7.2",),
        "gfx": (
            "gfx900", "gfx906", "gfx908", "gfx90a", "gfx942", "gfx950",
            "gfx1030", "gfx1100", "gfx1101", "gfx1102", "gfx1103",
            "gfx1200", "gfx1201", "gfx1150", "gfx1151",
        ),
        "source": "https://raw.githubusercontent.com/pytorch/pytorch/v2.14.0/.ci/docker/manywheel/build.sh",
    },
}

NOTES: tuple[str, ...] = (
    "cu118, cu121, cu124, rocm6.2 indexes: no cp312 wheels published in the 2.9.1-2.14.x range at all (cu118 tops out at torch 2.7.1, cu121/cu124/rocm6.2 stop well before cp312 wheels existed); published[idx] arrays are empty for these and are omitted from cuda_arch/rocm_arch.",
    "torchaudio's last published release is 2.11.0 (verified via METADATA: it has no Requires-Dist section at all, i.e. no torch pin, matching its 'maintenance phase' README notice). torchaudio 2.9.0/2.9.1/2.10.0 DO pin an exact torch version (Requires-Dist: torch==X, verified via METADATA). For torch versions 2.12.0-2.14.0 (newer than torchaudio's last release), the companion table pairs them with torchaudio 2.11.0 and flags 'torchaudio_note' since that pairing is unpinned/best-effort, not asserted by any wheel metadata.",
    "torchvision pins torch exactly via 'Requires-Dist: torch (==X)' in METADATA (PEP 658), verified for all published torchvision wheels used to build the companions table.",
    "Metadata/version pins were fetched via PEP 658 sidecar files (<wheel>.whl.metadata), which download.pytorch.org serves (data-dist-info-metadata attribute present in the simple index) — no full wheel downloads were needed.",
    "ROCm and xpu indexes publish x86_64 wheels only; no aarch64 cp312 wheels exist for any rocm*/xpu index in the target torch range, so companions[idx]['aarch64'] is {} for those indexes.",
    "cu132 never had a torchaudio wheel published (for any version in range), so companions['cu132'][*]['torchaudio'] is null for every torch version.",
    "v2.9.1's .ci/manywheel/build_cuda.sh has no $ARCH-based (aarch64) filtering of TORCH_CUDA_ARCH_LIST at all -- the identical arch string is used for both x86_64 and aarch64 builds at that tag (filtering by host arch was introduced starting at v2.10.0).",
    "CUDA arch lists for v2.9.1 through v2.12.1 come from the bash script .ci/manywheel/build_cuda.sh; v2.13.0 and v2.14.0 moved this logic to .ci/manywheel/build_env_setup.py (Python TORCH_CUDA_ARCH_LIST_TABLE). The bash-script versions hardcode '+PTX' unconditionally for the 12.9 (and 13.0, for v2.9.1/v2.10.0) case with no release/nightly distinction; the Python-table versions (v2.13.0+) explicitly omit '+PTX' for release/RC builds via _is_release_build()/_ptx_arches(), which is what actually ships on download.pytorch.org for those two tags. This is a genuine difference in the source, not a normalization choice made here.",
    "cu128 disappears from the torch_cuda_arch table at v2.13.0 and cu129 disappears at v2.14.0; this matches the wheel index directly (cu128 published torch up to 2.11.0 only, cu129 up to 2.13.0 only) and was used as a cross-check.",
    "ROCm gfx target lists and index applicability were read from .ci/docker/manywheel/build.sh's PYTORCH_ROCM_ARCH assignment per tag (manylinux2_28-builder:rocm* case branch), cross-checked against generate_binary_build_matrix.py's ROCM_ARCHES list and against which rocm* indexes actually published each torch version. No ROCm aarch64 arch differentiation exists in these scripts (no ROCm aarch64 wheels are published at all).",
    "Range filter applied throughout: >=2.9.1,<2.15 (i.e. 2.9.1 through 2.14.x).",
)
