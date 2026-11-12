# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Config compatibility guards for the residency change (group 6)."""

from pathlib import Path

from kaine.defaults import DEFAULT_CHAT_URL, language_section_chat_url


def test_language_chat_url_reads_from_config():
    assert (
        language_section_chat_url({"chat_url": "http://custom:1234/v1"}) == "http://custom:1234/v1"
    )


def test_language_chat_url_defaults_when_absent():
    assert language_section_chat_url({}) == DEFAULT_CHAT_URL
    assert "127.0.0.1" in DEFAULT_CHAT_URL
    assert "/v1" in DEFAULT_CHAT_URL


def test_no_first_party_llm_model_manager():
    forbidden = {
        "model_download",
        "model_manager",
        "weight_loader",
        "weight_download",
        "llm_loader",
        "llm_download",
    }
    for path in Path("kaine").rglob("*.py"):
        components = [Path(part).stem for part in path.parts]
        assert not any(component in forbidden for component in components)


def test_no_huggingface_download_in_residency():
    for path in Path("kaine/residency").rglob("*.py"):
        contents = path.read_text(encoding="utf-8")
        assert "from_pretrained" not in contents
        assert "hf_hub_download" not in contents
