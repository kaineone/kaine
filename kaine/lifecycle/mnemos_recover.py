# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Recovery CLI for an interrupted Mnemos preservation import.

Run as::

    python -m kaine.lifecycle.mnemos_recover --confirm-keep-current-store

If the interrupted import bundle still exists, re-running the revive command
is the correct fix. This command is for when the bundle is gone or the operator
chooses to keep the current store exactly as it stands.

Exit codes
----------
0  import flag cleared; store rescanned
1  no interrupted import is recorded
2  operator did not confirm keeping the current store
3  a cycle appears to be running
4  storage error during recovery
6  configuration error or backend needs no recovery
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None, *, out=None, err=None) -> int:
    """Operator recovery command for a blocked Mnemos store."""
    import argparse
    import asyncio
    import inspect
    import os
    from pathlib import Path

    if out is None:
        out = sys.stdout
    if err is None:
        err = sys.stderr

    parser = argparse.ArgumentParser(
        prog="python -m kaine.lifecycle.mnemos_recover",
        description="Clear a pending Mnemos import flag and rescan the store.",
    )
    parser.add_argument(
        "--config",
        default="config/kaine.toml",
        help="Merged runtime config path",
    )
    parser.add_argument(
        "--confirm-keep-current-store",
        action="store_true",
        help="Keep the current store and clear the interrupted-import flag",
    )
    args = parser.parse_args(argv)

    if not args.confirm_keep_current_store:
        err.write("mnemos-recover: no --confirm-keep-current-store flag.\n\n")
        err.write(
            "The store will be kept exactly as it stands. Strengths of traces the "
            "interrupted import wrote are relative to the pre-import log gain. "
            "Re-running the revive from its bundle is the correct fix when the "
            "bundle still exists.\n"
        )
        return 2

    import tomllib

    from kaine.config import (
        OPERATOR_CONFIG_PATH,
        ConfigShapeError,
        ProfileError,
        load_runtime_config,
    )

    config_path = Path(args.config)
    try:
        config = load_runtime_config(config_path, OPERATOR_CONFIG_PATH)
    except (
        ProfileError,
        ConfigShapeError,
        FileNotFoundError,
        OSError,
        tomllib.TOMLDecodeError,
    ) as exc:
        err.write(
            f"mnemos-recover: configuration error: {type(exc).__name__}: {exc}\n"
        )
        return 6

    from kaine.storage import install_data_root

    install_data_root(config)

    from kaine.lifecycle.liveness import cycle_process_state

    cycle_state = cycle_process_state()
    if cycle_state is True or cycle_state is None:
        err.write(
            "mnemos-recover: the cycle appears to be running; stop the entity first\n"
        )
        return 3

    from kaine.memory_kinds import MNEMOS_STORE_HEALTH_PATH
    from kaine.modules.mnemos.storage import (
        QdrantStorage,
        SqliteVecStorage,
        StorageError,
    )
    from kaine.storage import resolve
    from kaine.text_embedding import DEFAULT_LATENT_DIM

    mnemos = config.get("mnemos", {})
    backend = mnemos.get("backend", "qdrant").lower().replace("-", "_")

    if backend == "qdrant":
        qdrant_cfg = mnemos.get("qdrant", {})
        host = qdrant_cfg.get("host", "127.0.0.1")
        port = int(qdrant_cfg.get("port", 6533))
        api_key = qdrant_cfg.get("api_key")
        if not api_key:
            api_key = os.environ.get("KAINE_QDRANT_API_KEY")
        if not api_key:
            from kaine.bus.config import load_secrets_doc

            api_key = load_secrets_doc().get("qdrant", {}).get("api_key")
        if not api_key:
            err.write(
                "mnemos-recover: qdrant backend needs an api_key in "
                "[mnemos.qdrant], KAINE_QDRANT_API_KEY, or [qdrant] of "
                "secrets.toml\n"
            )
            return 6
        storage = QdrantStorage(
            latent_dim=DEFAULT_LATENT_DIM,
            host=host,
            port=port,
            api_key=api_key,
        )
    elif backend == "sqlite_vec":
        storage = SqliteVecStorage(latent_dim=DEFAULT_LATENT_DIM)
    else:
        err.write(
            f"mnemos-recover: backend {backend!r} persists nothing; "
            "there is nothing to recover\n"
        )
        return 6

    from kaine.modules.mnemos.memory import recover_interrupted_import

    collection_prefix = mnemos.get("collection_prefix", "mnemos_")
    budget_bytes = mnemos.get("storage_budget_bytes") or None
    health_path = resolve(MNEMOS_STORE_HEALTH_PATH)

    async def _run() -> dict:
        try:
            return await recover_interrupted_import(
                storage,
                collection_prefix=collection_prefix,
                budget_bytes=budget_bytes,
                health_path=health_path,
            )
        finally:
            close = storage.shutdown()
            if inspect.isawaitable(close):
                await close

    try:
        result = asyncio.run(_run())
    except StorageError as exc:
        err.write(
            f"mnemos-recover: storage error: {type(exc).__name__}: {exc}\n"
        )
        return 4

    if not result.get("cleared"):
        out.write("no interrupted import is recorded; nothing changed\n")
        return 1

    out.write(
        f"recovered store: {result['store_bytes']} bytes, "
        f"total strength {result['total']:.6f}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
