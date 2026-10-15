# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import itertools

import pytest

from kaine.modules.vocal.voices import (
    ChatterboxVoice,
    VoiceChoice,
    VoiceSelectionError,
    kokoro_gender,
    kokoro_speaker_name,
    normalize_gender,
    parse_chatterbox_voices,
    select_chatterbox_voice,
    select_kokoro_speaker,
)
from kaine.speech_manifest import MANIFEST

FAKE_SPEAKERS = ("bm_george", "af_sky", "am_adam", "zz", "af", "bf_emma")

CHATTERBOX_VOICES = [
    ChatterboxVoice("Olivia.wav", "Olivia"),
    ChatterboxVoice("abigail.wav", "Abigail"),
    ChatterboxVoice("Henry.wav", "Henry"),
]


def test_select_chatterbox_voice_is_deterministic():
    names = set()
    for permuted in itertools.permutations(CHATTERBOX_VOICES):
        choice = select_chatterbox_voice(permuted)
        names.add(choice.name)
        assert choice.source == "automatic"
    assert names == {"abigail.wav"}


def test_select_chatterbox_voice_gender_is_not_applied():
    for gender in ("male", "female", "any"):
        choice = select_chatterbox_voice(CHATTERBOX_VOICES, gender=gender)
        assert choice.name == "abigail.wav"
        assert choice.gender_applied is False
        if gender == "any":
            assert "reports no gender" not in choice.note
        else:
            assert "reports no gender" in choice.note


@pytest.mark.parametrize(
    "default_voice,expected_filename",
    [
        ("Henry.wav", "Henry.wav"),
        ("henry", "Henry.wav"),
        ("Olivia", "Olivia.wav"),
    ],
)
def test_select_chatterbox_voice_explicit_default_wins(default_voice, expected_filename):
    choice = select_chatterbox_voice(CHATTERBOX_VOICES, default_voice=default_voice)
    assert choice.name == expected_filename
    assert choice.source == "default_voice"
    assert choice.note == "named in [vocal].default_voice"


def test_select_chatterbox_voice_invalid_gender_ignored_when_default_matches():
    choice = select_chatterbox_voice(
        CHATTERBOX_VOICES,
        gender="robot",
        default_voice="Henry.wav",
    )
    assert choice.name == "Henry.wav"
    assert choice.source == "default_voice"


def test_select_chatterbox_voice_unknown_default_raises():
    with pytest.raises(VoiceSelectionError) as exc_info:
        select_chatterbox_voice(CHATTERBOX_VOICES, default_voice="nobody")
    message = str(exc_info.value)
    assert "[vocal].default_voice" in message
    assert "3 voices" in message


def test_select_chatterbox_voice_empty_list_raises():
    with pytest.raises(VoiceSelectionError) as exc_info:
        select_chatterbox_voice([])
    message = str(exc_info.value)
    assert "[vocal].predefined_voice_id" in message
    assert "\n" not in message


def test_parse_chatterbox_voices_real_server_shape():
    payload = [
        {"display_name": "Abigail", "filename": "Abigail.wav"},
        {"display_name": "", "filename": "Henry.wav"},
        {"filename": ""},
    ]
    voices = parse_chatterbox_voices(payload)
    assert voices == [
        ChatterboxVoice("Abigail.wav", "Abigail"),
        ChatterboxVoice("Henry.wav", "Henry"),
    ]


def test_parse_chatterbox_voices_plain_strings():
    voices = parse_chatterbox_voices(["Olivia.wav", "", "henry.wav"])
    assert voices == [
        ChatterboxVoice("Olivia.wav", "Olivia"),
        ChatterboxVoice("henry.wav", "henry"),
    ]


def test_parse_chatterbox_voices_legacy_dict():
    voices = parse_chatterbox_voices({"Abigail.wav": None, "Henry.wav": None})
    assert voices == [
        ChatterboxVoice("Abigail.wav", "Abigail"),
        ChatterboxVoice("Henry.wav", "Henry"),
    ]


def test_parse_chatterbox_voices_drops_duplicates_and_skips_bad_elements():
    payload = [
        {"display_name": "Abigail", "filename": "Abigail.wav"},
        {"display_name": "Abi", "filename": "Abigail.wav"},
        42,
        "Henry.wav",
        {"display_name": "No filename"},
    ]
    voices = parse_chatterbox_voices(payload)
    assert voices == [
        ChatterboxVoice("Abigail.wav", "Abigail"),
        ChatterboxVoice("Henry.wav", "Henry"),
    ]


@pytest.mark.parametrize("payload", [None, 42])
def test_parse_chatterbox_voices_rejects_unexpected_types(payload):
    with pytest.raises(VoiceSelectionError) as exc_info:
        parse_chatterbox_voices(payload)
    assert type(payload).__name__ in str(exc_info.value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "any"),
        ("", "any"),
        (" Female ", "female"),
        ("MALE", "male"),
        ("any", "any"),
    ],
)
def test_normalize_gender_valid(value, expected):
    assert normalize_gender(value) == expected


@pytest.mark.parametrize("value", ["robot", 3])
def test_normalize_gender_invalid(value):
    with pytest.raises(ValueError) as exc_info:
        normalize_gender(value)
    assert "[vocal].voice_gender" in str(exc_info.value)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("af", "female"),
        ("am_adam", "male"),
        ("bf_emma", "female"),
        ("bm_lewis", "male"),
        ("zz", None),
        ("afx", None),
        ("", None),
        ("AF", None),
        ("a_f", None),
    ],
)
def test_kokoro_gender(name, expected):
    assert kokoro_gender(name) == expected


def test_select_kokoro_speaker_any():
    choice = select_kokoro_speaker(FAKE_SPEAKERS, gender="any")
    assert choice == VoiceChoice(
        name="af",
        speaker_id=4,
        source="automatic",
        gender_applied=False,
        note="first of 6 kokoro-en speakers in sorted order",
    )


def test_select_kokoro_speaker_female():
    choice = select_kokoro_speaker(FAKE_SPEAKERS, gender="female")
    assert choice.name == "af"
    assert choice.speaker_id == 4
    assert choice.gender_applied is True
    assert "first female speaker" in choice.note


def test_select_kokoro_speaker_male():
    choice = select_kokoro_speaker(FAKE_SPEAKERS, gender="male")
    assert choice.name == "am_adam"
    assert choice.speaker_id == 2
    assert choice.gender_applied is True


def test_select_kokoro_speaker_explicit_default():
    choice = select_kokoro_speaker(FAKE_SPEAKERS, default_voice="BF_EMMA")
    assert choice.name == "bf_emma"
    assert choice.speaker_id == 5
    assert choice.source == "default_voice"


def test_select_kokoro_speaker_unknown_default_raises():
    with pytest.raises(VoiceSelectionError) as exc_info:
        select_kokoro_speaker(FAKE_SPEAKERS, default_voice="nobody")
    assert "[vocal].default_voice" in str(exc_info.value)


def test_select_kokoro_speaker_no_matching_gender():
    small_table = ("af", "bf_emma")
    with pytest.raises(VoiceSelectionError) as exc_info:
        select_kokoro_speaker(small_table, gender="male", model_id="test-model")
    assert "test-model" in str(exc_info.value)
    assert "[vocal].voice_gender" in str(exc_info.value)


def test_select_kokoro_speaker_empty_table_any():
    choice = select_kokoro_speaker([], gender="any")
    assert choice.name == ""
    assert choice.speaker_id == 0
    assert choice.source == "automatic"


def test_select_kokoro_speaker_empty_table_gender_raises():
    with pytest.raises(VoiceSelectionError) as exc_info:
        select_kokoro_speaker([], gender="female")
    assert "[vocal].voice_gender" in str(exc_info.value)


def test_select_kokoro_speaker_empty_table_default_raises():
    with pytest.raises(VoiceSelectionError) as exc_info:
        select_kokoro_speaker([], default_voice="af")
    assert "cannot be checked" in str(exc_info.value)


def test_real_kokoro_manifest_speakers():
    speakers = MANIFEST["kokoro-en"].speakers
    assert len(speakers) == 11
    for name in speakers:
        assert kokoro_gender(name) is not None

    any_choice = select_kokoro_speaker(speakers, gender="any")
    assert any_choice.speaker_id == 0
    assert any_choice.name == "af"

    female_choice = select_kokoro_speaker(speakers, gender="female")
    assert female_choice.speaker_id == 0

    male_choice = select_kokoro_speaker(speakers, gender="male")
    assert male_choice.speaker_id == 5
    assert male_choice.name == "am_adam"


@pytest.mark.parametrize(
    "speaker_id,expected",
    [
        (2, "am_adam"),
        (0, "bm_george"),
        (-1, ""),
        (len(FAKE_SPEAKERS), ""),
    ],
)
def test_kokoro_speaker_name(speaker_id, expected):
    assert kokoro_speaker_name(FAKE_SPEAKERS, speaker_id) == expected
