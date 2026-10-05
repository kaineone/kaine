# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The process-wide data root never leaks from one test into the next."""

from kaine import storage

_BASELINE = storage.data_root()


def test_a_test_may_install_a_data_root_without_resetting_it(tmp_path):
    storage.set_data_root(tmp_path)
    assert storage.data_root() == tmp_path.resolve()


def test_the_next_test_sees_the_previous_data_root():
    # Runs after the test above (same file, same worker, file order).
    assert storage.data_root() == _BASELINE
