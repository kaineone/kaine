import argparse
from typing import Any, Dict

from .config import load_runtime_config

def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run KAINE questionnaire")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include full set of questionnaire keys (including advanced tiers)",
    )
    return parser.parse_args(argv)

def filter_keys_for_basic_tier(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``config`` containing only keys that belong to the basic tier.

    The basic tier is defined by the shipped configuration's ``[tier.basic]`` table.
    Advanced keys (those not present under that table) are omitted when the
    questionnaire is run without ``--full``.
    """
    # Load the shipped configuration to discover which top‑level keys belong to the basic tier
    from .config import SHIPPED_CONFIG_PATH
    import tomllib

    with SHIPPED_CONFIG_PATH.open("rb") as fh:
        shipped = tomllib.load(fh)

    basic_keys = set(shipped.get("tier", {}).get("basic", {}).keys())
    # Preserve the original structure but drop any top‑level entries not in basic_keys
    return {k: v for k, v in config.items() if k in basic_keys}

def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)

    # Load the full runtime configuration (includes all layers)
    config = load_runtime_config()

    # If the user did not request the full questionnaire, limit to basic tier keys
    if not args.full:
        config = filter_keys_for_basic_tier(config)

    # The rest of the questionnaire logic operates on ``config``.
    # For illustration purposes we simply print the resulting keys.
    for key in sorted(config):
        print(f"{key}: {config[key]!r}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())