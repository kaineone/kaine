#!/usr/bin/env python3
import sys
import argparse
from .config import load_config, merge_configs
from .validation import validate_config_shape

def main():
    parser = argparse.ArgumentParser(description="KAINE preboot utility")
    parser.add_argument('--config', required=True, help='Path to configuration file')
    args = parser.parse_args()

    # Existing checks and processing...
    try:
        user_config = load_config(args.config)
        merged_config = merge_configs(user_config)
    except Exception as e:
        sys.stderr.write(f"Error loading configuration: {e}\n")
        sys.exit(1)

    # Existing validation steps...

    # Append-only ConfigValid check
    if not validate_config_shape(merged_config):
        sys.stderr.write("Config shape validation failed.\n")
        sys.exit(1)

    # Continue with the rest of the preboot process...
    # ...

if __name__ == "__main__":
    main()