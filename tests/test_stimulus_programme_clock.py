# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The seekable programme clock (stimulus-control-act, design D2).

Seeking wraps at both ends and never ends the viewing; the viewing ends when
perceived programme time reaches channel 0's length; without a seek the clock
maps time exactly as the plain playlist clock does.
"""
from __future__ import annotations

import pytest

from kaine.cycle.programme_end import ProgrammeEndWatcher
from kaine.modules.effectors.stimulus.programme import ProgrammeClock
from kaine.modules.vision.feed import PlaylistClock


class _Mono:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _clocks(durations, segments=None):
    mono = _Mono()
    plain = PlaylistClock(len(durations), clock=mono)
    prog = ProgrammeClock(len(durations), segments=segments, clock=mono)
    for i, d in enumerate(durations):
        plain.set_duration(i, d)
        prog.set_duration(i, d)
    plain.start()
    prog.start()
    return mono, plain, prog


def _ended(clock) -> bool:
    return ProgrammeEndWatcher._programme_ended(clock, clock.item_count)


def test_without_a_seek_the_mapping_is_the_plain_clocks():
    mono, plain, prog = _clocks([2.0, 3.0, 1.5])
    for step in range(0, 80):
        mono.t = 100.0 + step * 0.1
        assert prog.locate() == plain.locate()
    # Past the end both report the exhausted index.
    mono.t = 100.0 + 6.5
    assert prog.locate() == plain.locate() == (3, 0.0)


def test_pause_is_excluded_from_perceived_time():
    mono, _plain, prog = _clocks([2.0, 3.0])
    mono.t = 101.0
    prog.pause("entity")
    mono.t = 150.0
    assert prog.locate() == (0, pytest.approx(1.0))
    prog.resume("entity")
    mono.t = 151.5
    assert prog.locate() == (1, pytest.approx(0.5))


def test_next_moves_to_the_start_of_the_next_item():
    mono, _plain, prog = _clocks([2.0, 3.0, 1.5])
    mono.t = 100.5
    assert prog.seek(+1) == 1
    assert prog.locate() == (1, pytest.approx(0.0))
    mono.t = 101.0
    assert prog.locate() == (1, pytest.approx(0.5))


def test_next_on_the_last_item_wraps_to_the_first_and_does_not_end():
    mono, _plain, prog = _clocks([2.0, 3.0, 1.5])
    mono.t = 105.0  # item 2 at 0.0 of perceived 5.0
    assert prog.locate()[0] == 2
    assert prog.seek(+1) == 0
    assert prog.locate() == (0, pytest.approx(0.0))
    assert not _ended(prog)


def test_previous_on_the_first_item_wraps_to_the_last():
    mono, _plain, prog = _clocks([2.0, 3.0, 1.5])
    mono.t = 100.2
    assert prog.seek(-1) == 2
    assert prog.locate() == (2, pytest.approx(0.0))


def test_skipping_never_changes_the_viewing_length():
    mono, _plain, prog = _clocks([2.0, 3.0, 1.5])  # 6.5 s programme
    for k in range(1, 13):
        mono.t = 100.0 + 0.5 * k
        prog.seek(+1)
        assert not _ended(prog), "a skip ended the viewing"
    # Perceived time still short of 6.5 s: the presented position wraps.
    mono.t = 106.4
    assert prog.locate()[0] < 3
    assert not _ended(prog)
    mono.t = 106.5
    assert prog.locate() == (3, 0.0)
    assert _ended(prog)


def test_running_past_a_channels_end_wraps_and_changes_the_epoch():
    mono, _plain, prog = _clocks([2.0, 3.0])
    mono.t = 101.0
    prog.seek(+1)  # item 1 from perceived 1.0
    epoch = prog.position_epoch()
    mono.t = 104.5  # 3.5 s into item 1 (3 s long): wrapped to item 0
    assert prog.locate() == (0, pytest.approx(0.5))
    assert prog.position_epoch() != epoch


def test_a_seek_changes_the_epoch_even_onto_the_same_item():
    mono, _plain, prog = _clocks([4.0])
    mono.t = 101.0
    epoch = prog.position_epoch()
    assert prog.seek(+1) == 0
    assert prog.locate() == (0, pytest.approx(0.0))
    assert prog.position_epoch() != epoch


def test_channels_and_the_viewing_length_of_channel_zero():
    # Channel 0: items 0-1 (8 s); channel 1: items 2-3 (2 s + 3 s).
    mono, _plain, prog = _clocks([4.0, 4.0, 2.0, 3.0], segments=[(0, 2), (2, 2)])
    assert prog.viewing_length == pytest.approx(8.0)
    mono.t = 101.0
    assert prog.switch_channel(1) == 2
    assert prog.locate() == (2, pytest.approx(0.0))
    mono.t = 103.5  # 2.5 s into channel 1: its second item
    assert prog.locate() == (3, pytest.approx(0.5))
    assert prog.channel == 1
    # Within channel 1, next wraps inside channel 1.
    prog.seek(+1)
    assert prog.locate() == (2, pytest.approx(0.0))
    mono.t = 107.6  # 4.1 s after the seek: channel 1's second item, never channel 0
    assert prog.locate() == (3, pytest.approx(2.1))
    mono.t = 107.99
    assert not prog.ended()
    mono.t = 108.0  # perceived 8 s = channel 0's length: the viewing has ended
    assert prog.ended()
    assert prog.locate() == (4, 0.0)


def test_switch_to_an_unknown_channel_is_refused():
    from kaine.modules.effectors.stimulus.config import StimulusControlError

    _mono, _plain, prog = _clocks([2.0])
    with pytest.raises(StimulusControlError):
        prog.switch_channel(1)


def test_channels_must_cover_every_item():
    with pytest.raises(ValueError):
        ProgrammeClock(3, segments=[(0, 1), (2, 1)])
    with pytest.raises(ValueError):
        ProgrammeClock(3, segments=[(0, 2)])


def test_unmeasured_items_keep_the_plain_walk_and_refuse_a_seek():
    from kaine.modules.effectors.stimulus.config import StimulusControlError

    mono = _Mono()
    plain = PlaylistClock(2, clock=mono)
    prog = ProgrammeClock(2, clock=mono)
    plain.start()
    prog.start()
    plain.set_duration(0, 1.0)
    prog.set_duration(0, 1.0)
    mono.t = 103.0
    assert prog.locate() == plain.locate()
    with pytest.raises(StimulusControlError):
        prog.seek(+1)


def test_running_past_a_later_channels_end_wraps_inside_that_channel():
    mono, _plain, prog = _clocks([10.0, 2.0], segments=[(0, 1), (1, 1)])
    mono.t = 101.0
    prog.switch_channel(1)
    epoch = prog.position_epoch()
    mono.t = 103.5  # 2.5 s into a 2 s channel: wrapped, still channel 1
    assert prog.locate() == (1, pytest.approx(0.5))
    assert prog.position_epoch() != epoch
    assert prog.current_position() == (1, 1, 0)


def test_position_and_epoch_come_from_one_reading():
    mono, _plain, prog = _clocks([2.0, 3.0, 1.5])
    mono.t = 101.0
    idx, offset, epoch = prog.locate_with_epoch()
    assert (idx, offset) == prog.locate() and epoch == prog.position_epoch()
    prog.seek(+1)
    idx2, offset2, epoch2 = prog.locate_with_epoch()
    assert (idx2, offset2) == (1, pytest.approx(0.0)) and epoch2 != epoch
    mono.t = 106.5
    assert prog.locate_with_epoch()[:2] == (3, 0.0)
