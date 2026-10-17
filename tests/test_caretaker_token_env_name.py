# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import re

import pytest

from kaine.cycle.caretaker import (
    CARETAKER_TOKEN_ENV_PREFIX,
    CaretakerConfig,
    CaretakerConfigError,
    load_token,
)

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@pytest.mark.parametrize(
    "name",
    [
        "ntfy",
        "gotify_1",
        "a",
        "x" * 64,
        "0lead",
    ],
)
def test_accepted_token_name(tmp_path, name):
    section = {
        "channels": [
            {"kind": "http", "url": "http://10.0.0.1/x", "token_name": name}
        ]
    }
    cfg = CaretakerConfig.from_section(section)

    assert cfg.channels[0].token_name == name

    env_name = CARETAKER_TOKEN_ENV_PREFIX + name.upper()
    assert _ENV_NAME.match(env_name)

    assert (
        load_token(
            name,
            secrets_path=tmp_path / "absent.toml",
            env={env_name: "tok"},
        )
        == "tok"
    )


@pytest.mark.parametrize(
    "name",
    [
        "ntfy-1",
        "ntfy.x",
        "has space",
        "",
        "Upper",
        "x" * 65,
        "é",
    ],
)
def test_refused_token_name(name):
    section = {
        "channels": [
            {"kind": "http", "url": "http://10.0.0.1/x", "token_name": name}
        ]
    }

    with pytest.raises(CaretakerConfigError) as excinfo:
        CaretakerConfig.from_section(section)

    msg = str(excinfo.value)
    assert "token_name" in msg
    assert r"^[a-z0-9_]{1,64}$" in msg
    assert "channels[0]" in msg


def test_non_string_token_name_refused():
    section = {
        "channels": [
            {"kind": "http", "url": "http://10.0.0.1/x", "token_name": 123}
        ]
    }

    with pytest.raises(CaretakerConfigError) as excinfo:
        CaretakerConfig.from_section(section)

    msg = str(excinfo.value)
    assert "token_name" in msg
    assert r"^[a-z0-9_]{1,64}$" in msg
    assert "channels[0]" in msg
