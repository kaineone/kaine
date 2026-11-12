# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Export an acoustic encoder's segment module to ONNX (and optionally dynamic int8)."""

from __future__ import annotations

import argparse
from pathlib import Path

from kaine.model_paths import models_dir
from kaine.modules.audition import onnx_export
from kaine.modules.audition.ssl_encoders import PINS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("encoder", choices=sorted(PINS))
    parser.add_argument("--output", type=Path, required=True, help="output directory")
    parser.add_argument("--weights-dir", type=Path, default=None)
    parser.add_argument("--int8", action="store_true", help="also write a dynamic-int8 model")
    parser.add_argument("--opset", type=int, default=17)
    args = parser.parse_args(argv)

    weights_dir = args.weights_dir or models_dir() / PINS[args.encoder][2]
    export = getattr(onnx_export, f"export_{args.encoder}")
    onnx_path = export(weights_dir, args.output / f"{args.encoder}.onnx", opset=args.opset)
    print(onnx_path)
    if args.int8:
        print(
            onnx_export.quantize_dynamic_int8(onnx_path, args.output / f"{args.encoder}.int8.onnx")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
