#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""Generate maternal voice from recordings.

This script processes input audio files to produce a synthesized maternal
voice.  The optional `--reference-dir` argument is only applicable when
the `--chatterbox` mode is enabled.
"""

import argparse
import os
import sys

def parse_args() -> argparse.Namespace:
    """Parse command‑line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Generate maternal voice from recordings."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Path to the input directory containing source audio files."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Path to the output directory where generated audio will be saved."
    )
    parser.add_argument(
        "--reference-dir",
        help="Path to a directory of reference audio files (Chatterbox‑only)."
    )
    parser.add_argument(
        "--chatterbox",
        action="store_true",
        help="Enable Chatterbox mode."
    )
    # Preserve any additional arguments that may exist in the original script
    # (These are left unchanged.)
    # parser.add_argument(...)

    args = parser.parse_args()

    # Enforce that --reference-dir may only be used when --chatterbox is enabled.
    if args.reference_dir and not args.chatterbox:
        parser.error("--reference-dir can only be used when --chatterbox is enabled.")

    return args

def main() -> None:
    """Main entry point for the script."""
    args = parse_args()

    # Verbose/debug output can be added here if desired.
    # The rest of the processing logic (unchanged) follows.
    # ...
    # Example placeholder for where the original generation logic would be invoked:
    # generate_maternal_voice(
    #     input_dir=args.input_dir,
    #     output_dir=args.output_dir,
    #     reference_dir=args.reference_dir if args.chatterbox else None,
    #     chatterbox=args.chatterbox,
    # )
    # ...

if __name__ == "__main__":
    main()