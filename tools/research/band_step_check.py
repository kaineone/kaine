# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Offline band-step check for developmental-stimulus-progress (design D4). No entity, no services.

Renders the developmental soundscape with the real generator
(``StimulusSourceProceduralAudioStream.pcm_at``, the real maternal voice and the
real hearing band), cuts it into the windows the live microphone delivers with
general audition on (``LiveMicConfig.window_ms // vad_frame_ms`` blocks, wrapped
by ``live.encode_wav``), and hands each window to the real ``Audition`` module's
acoustic path (``_perceive_acoustic``: arousal window, spectral encoder, acoustic
forward model, published ``audition.perception`` event). Each published event,
and a ``development.hearing_stage`` event at every step, goes to the real
``Affect`` module's peer-event handler, so audition's learning-progress bins are
the affect module's own, with its own restart. Once a simulated second the
harness reads ``Affect.audition_learning_progress(stage)``, as the hearing-stage
watch does, and feeds it to a ``HearingStageState`` with the shipped parameters
(the step it would take is recorded; the schedule here is ``--schedule``).

Simplifications, all stated in the record: no workspace, so the forward model's
broadcast context is absent (None, as before the first broadcast); arousal is
held at the affect baseline; awake time equals stimulus time (no rests).

``--live`` removes those three (the live-gap check, developmental-stimulus-progress
D5b and task 3.1), with real modules and no services:
- Arousal: the shipped affect module (``make_affect`` on ``[affect]``, drives and
  coupling included, regulation off as in the developmental phase) is the arousal
  provider audition's attention window reads, as the cycle wires it; perceptual
  alerts raise it. The affect module ticks and publishes ``affect.state`` once a
  second, as its own timer does, and on every broadcast.
- Rests: the sleep module's developmental state cycle from ``[sleep]``, a rest of
  ``developmental_rest_s`` after every ``T_act = rest * (1 - s_q) / s_q`` awake
  seconds. During a rest the stimulus plays on, audition perceives with its forward
  model suspended (``_in_sleep``), the affect module keeps binning errors on the
  entity clock, awake time and the hearing-stage dwell stand still, and the rest
  ends with the affect module's affective reset, the sleep pipeline's last phase.
- Broadcast context: the real ``Workspace`` with the shipped salience
  (``RuleBasedSalience`` over ``make_salience_factors`` and a ``NoveltyTracker``,
  ``top_k``, ``publication_threshold``) selects among the audition and affect
  events gathered since the last broadcast, at the rate the real
  ``AccessRateController`` sets on 0.1 s processing ticks from ``[cycle]``. Each
  broadcast goes to ``Audition.on_workspace`` (its prediction context) and
  ``Affect.on_workspace``. The broadcast holds no vision, interoception or
  self-rhythm events (those modules do not run here), and the coherence layer and
  broadcast feedback are off.
The live run also feeds every ``affect.state`` to the welfare observer's own
``AffectWelfareTally`` (rests as sleeps), for boredom's deprivation share over
awake time (task 3.2), overall and per stage.

Arms: ``shipped`` is the shipped stimulus with its added sounds as configured (the
real ``AddedSoundsLayer`` with the shipped melody and outside-voice takes); the
run records the shipped stimulus version (``kaine.boot.stimulus_version``).
``none`` is the stimulus without added sounds. ``melody`` adds a harness rendering of
the change's recurring melody (design D2: "Twinkle, Twinkle, Little Star", G4 to
E5, harmonic tones, p_m = 0.02 per slot without speech). ``melody_proxy`` also
adds a SYNTHETIC PROXY for the outside voice (design D3 needs Chatterbox, which
this harness does not run): a harmonic source at 100-130 Hz through formant
envelopes, at the soundscape RMS, p_x = 0.05. The proxy is a stand-in for its
spectrum only; it is not the change's outside voice.

Output: one compressed .npz per run with per-report errors, per-second learning
progress, per-minute band powers and mean embeddings, and the step times. No
audio is written.

usage: band_step_check.py --seed N --arm shipped|none|melody|melody_proxy
       --schedule fixed:SECONDS|rule --out PATH.npz [--live] [--repo REPO]

With --live the fixed schedule and --max-hours count awake seconds.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # CPU only

import numpy as np

# Regions of the spectrum that each step opens (Hz): below 158 (step 2), 158-354
# (step 1), 354-707 (stage 0), 707-1732 (step 3), 1732-3000 (step 4), above 3000.
REGION_EDGES = (0.0, 158.1, 353.6, 707.1, 1732.1, 3000.0, 8000.0)

SALT_MELODY = 0x7A10
SALT_OUTSIDE = 0x7A20

# "Twinkle, Twinkle, Little Star" in G major from G4 (Partanen et al. 2013 played
# this tune; design D2). (MIDI note, beats).
_G4, _A4, _B4, _C5, _D5, _E5 = 67, 69, 71, 72, 74, 76
_PHRASE_A = [(_G4, 1), (_G4, 1), (_D5, 1), (_D5, 1), (_E5, 1), (_E5, 1), (_D5, 2),
             (_C5, 1), (_C5, 1), (_B4, 1), (_B4, 1), (_A4, 1), (_A4, 1), (_G4, 2)]
_PHRASE_B = [(_D5, 1), (_D5, 1), (_C5, 1), (_C5, 1), (_B4, 1), (_B4, 1), (_A4, 2)]
MELODY_NOTES = _PHRASE_A + _PHRASE_B + _PHRASE_B + _PHRASE_A


def _midi_hz(m: int) -> float:
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def _ramp(n: int, sr: int, ramp_s: float = 0.5) -> np.ndarray:
    r = min(n // 2, int(ramp_s * sr))
    env = np.ones(n)
    if r > 0:
        w = 0.5 - 0.5 * np.cos(np.pi * np.arange(r) / r)
        env[:r] = w
        env[-r:] = w[::-1]
    return env


def render_melody(sr: int, tempo: float) -> np.ndarray:
    """Harmonic tones (8 partials, 1/k), smooth note envelopes, unit RMS."""
    beat = 0.5 / tempo
    parts = []
    for midi, beats in MELODY_NOTES:
        f0 = _midi_hz(midi)
        dur = beats * beat
        n = int(dur * sr)
        t = np.arange(n) / sr
        tone = np.zeros(n)
        for k in range(1, 9):
            if k * f0 < sr / 2:
                tone += np.sin(2 * np.pi * k * f0 * t) / k
        a = int(0.02 * sr)
        rel = int(0.06 * sr)
        env = np.exp(-t / (1.2 * dur + 0.2))
        env[:a] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
        env[-rel:] *= np.linspace(1.0, 0.0, rel)
        gap = np.zeros(int(0.04 * sr))
        parts += [tone * env, gap]
    x = np.concatenate(parts)
    return x / np.sqrt(np.mean(x * x))


_VOWELS = ((730, 1090, 2440), (270, 2290, 3010), (300, 870, 2240), (530, 1840, 2480), (570, 840, 2410))


def render_outside_proxy(sr: int, seed: int, slot: int, seconds: float) -> np.ndarray:
    """A low male-range harmonic source through formant envelopes, syllabic and phrased. Unit RMS over voiced parts."""
    from kaine.modules.perception_prng import keyed_u64, unit_float

    def u(i: int) -> float:
        return unit_float(keyed_u64(seed, slot * 4096 + i, SALT_OUTSIDE | 0x1))

    n = int(seconds * sr)
    t = np.arange(n) / sr
    f0b = 100.0 + 30.0 * u(0)
    f0 = f0b * (1.0 + 0.08 * np.sin(2 * np.pi * (0.25 + 0.2 * u(1)) * t + 6.28 * u(2))) * (1.0 - 0.1 * t / seconds)
    phase = 2 * np.pi * np.cumsum(f0) / sr
    # Syllables of 0.18-0.32 s, each with a vowel; phrases of 6-12 syllables, pauses 0.4-1.0 s.
    amp = np.zeros(n)
    form = np.zeros((n, 3))
    pos, i = int(0.3 * sr), 3
    while pos < n:
        for _ in range(6 + int(7 * u(i))):
            ln = int((0.18 + 0.14 * u(i + 1)) * sr)
            if pos + ln >= n:
                break
            v = _VOWELS[int(5 * u(i + 2)) % 5]
            amp[pos:pos + ln] = np.sin(np.pi * np.arange(ln) / ln) ** 0.7
            form[pos:pos + ln] = v
            pos += ln
            i += 3
        pos += int((0.4 + 0.6 * u(i)) * sr)
        i += 1
    form[amp == 0] = _VOWELS[0]
    x = np.zeros(n)
    for k in range(1, 31):
        fk = k * f0
        g = np.zeros(n)
        for j, bw in enumerate((80.0, 100.0, 120.0)):
            g += (0.9 ** j) / (1.0 + ((fk - form[:, j]) / bw) ** 2)
        x += np.where(fk < 3000.0, g / k, 0.0) * np.sin(k * phase)
    x *= amp
    voiced = amp > 0
    rms = math.sqrt(float(np.mean(x[voiced] ** 2))) if voiced.any() else 1.0
    return x / rms


class AddedSoundsVoice:
    """The maternal voice layer plus the harness's added sounds, mixed before the hearing band.

    A slot with maternal speech holds no added sound; otherwise a keyed draw on
    (seed, slot) below p_m holds the melody, else one below p_x the outside-voice proxy.
    """

    def __init__(self, voice, *, seed: int, sr: int, background_rms: float, arm: str,
                 p_m: float = 0.02, p_x: float = 0.05) -> None:
        from kaine.modules.audition.hearing_band import band_taps

        self._voice = voice
        self._seed = int(seed)
        self._sr = int(sr)
        self._arm = arm
        self._p_m = p_m
        self._p_x = p_x if arm == "melody_proxy" else 0.0
        self._slot_n = int(round(voice.params.slot_seconds * sr))
        self._lp = band_taps(None, 3000.0, float(sr))  # the intrauterine path's 3000 Hz low-pass, as the voice
        self._melody = {}
        for tempo in (0.9, 1.0, 1.1):
            m = np.convolve(render_melody(sr, tempo), self._lp, mode="same")
            self._melody[tempo] = m / np.sqrt(np.mean(m * m))
        self._voice_target = voice.target_rms  # the maternal voice's level above the soundscape
        self._bg = float(background_rms)  # the soundscape's RMS
        self._cache: dict[int, np.ndarray | None] = {}
        self.slot_kinds: dict[int, str] = {}

    @property
    def repertoire(self):
        return self._voice.repertoire

    @property
    def params(self):
        return self._voice.params

    @property
    def headroom(self) -> float:
        return self._voice.headroom

    @property
    def target_rms(self) -> float:
        return self._voice.target_rms

    def _slot_audio(self, slot: int, awake: float) -> np.ndarray | None:
        if slot in self._cache:
            return self._cache[slot]
        from kaine.modules.perception_prng import keyed_u64, unit_float

        out = None
        kind = "none"
        if not self._voice.plan_for(slot, awake):
            um = unit_float(keyed_u64(self._seed, slot, SALT_MELODY | 0x1))
            ux = unit_float(keyed_u64(self._seed, slot, SALT_OUTSIDE | 0x2))
            if um < self._p_m:
                tempo = (0.9, 1.0, 1.1)[int(3 * unit_float(keyed_u64(self._seed, slot, SALT_MELODY | 0x2))) % 3]
                jit = 10.0 ** ((2 * unit_float(keyed_u64(self._seed, slot, SALT_MELODY | 0x3)) - 1) * 3.0 / 20.0)
                m = self._melody[tempo] * self._voice_target * jit
                m = m * _ramp(m.size, self._sr)
                out = np.zeros(self._slot_n)
                off = int(unit_float(keyed_u64(self._seed, slot, SALT_MELODY | 0x4)) * max(1, self._slot_n - m.size))
                out[off:off + m.size] = m[: self._slot_n - off]
                kind = "melody"
            elif ux < self._p_x:
                v = render_outside_proxy(self._sr, self._seed, slot, 24.0)
                v = np.convolve(v, self._lp, mode="same") * self._bg
                v = v * _ramp(v.size, self._sr)
                out = np.zeros(self._slot_n)
                off = int(2.0 * self._sr)
                out[off:off + v.size] = v[: self._slot_n - off]
                kind = "outside_proxy"
        self._cache[slot] = out
        self.slot_kinds[slot] = kind
        for old in [k for k in self._cache if k < slot - 2]:
            del self._cache[old]
        return out

    def plan_for(self, slot: int, awake: float):
        return self._voice.plan_for(slot, awake)

    def render(self, start: int, n: int, awake_seconds: float) -> np.ndarray:
        out = self._voice.render(start, n, awake_seconds)
        s0, s1 = start // self._slot_n, (start + n - 1) // self._slot_n
        for slot in range(s0, s1 + 1):
            a = self._slot_audio(slot, awake_seconds)
            if a is None:
                continue
            lo = max(start, slot * self._slot_n)
            hi = min(start + n, (slot + 1) * self._slot_n)
            out[lo - start:hi - start] += a[lo - slot * self._slot_n:hi - slot * self._slot_n]
        return out


class _Live:
    """The live conditions of ``--live``: rests, broadcasts and the welfare tally."""

    PROCESSING_DT_S = 0.1

    def __init__(self, cfg: dict, affect, audition, clock, affect_bus) -> None:  # noqa: ANN001
        from kaine.boot.wiring import make_salience_factors
        from kaine.cycle.access_rate import AccessRateConfig, AccessRateController
        from kaine.cycle.affect_state import AffectStateProvider
        from kaine.evaluation.observers.welfare_observer import (
            _AFFECT_SAMPLE_GAP_CAP_S,
            _DEFAULT_NEGATIVE_VALENCE_BAR,
            AffectWelfareTally,
        )
        from kaine.workspace import NoveltyTracker, RuleBasedSalience, Workspace
        from kaine.workspace.strategies import build_drive_sources

        self._affect = affect
        self._audition = audition
        self._clock = clock
        self._fbus = affect_bus
        self._fbus_seen = 0
        syn = dict(cfg.get("workspace") or {})
        self.provider = AffectStateProvider()
        modulator, goal, _ = make_salience_factors(
            cfg, self.provider,
            drive_sources=build_drive_sources({"audition": audition.relieves_drives, "affect": affect.relieves_drives}),
        )
        self.workspace = Workspace(
            strategy=RuleBasedSalience(
                novelty=NoveltyTracker(window=int(syn.get("novelty_window", 32))),
                goal_scorer=goal, affect_modulator=modulator,
            ),
            top_k=int(syn.get("top_k", 5)),
            publication_threshold=float(syn.get("publication_threshold", 0.35)),
        )
        cyc = dict(cfg.get("cycle") or {})
        self.resting_hz = float(cyc.get("experiential_rate_hz", 3.333))
        self.ceiling_hz = float(cyc.get("processing_rate_hz", 10.0))
        arc = AccessRateConfig.from_section(
            cyc.get("access_rate"), default_baseline=float((cfg.get("affect") or {}).get("baseline_arousal", 0.3))
        )
        self.access = AccessRateController(arc) if arc.enabled else None
        sleep = dict(cfg.get("sleep") or {})
        self.rest_s = float(sleep.get("developmental_rest_s", 1410.0))
        share = float(sleep.get("developmental_quiescent_share", 0.32))
        self.t_act = self.rest_s * (1.0 - share) / share
        self.resting = False
        self.rest_until = 0.0
        self.awake_since_rest = 0.0
        self.rests: list[tuple[float, float]] = []
        self.pending: list = []
        self.new_this_tick: list = []
        self.tick_acc = 0.0
        self.exp_acc = 0.0
        self.tick_index = 0
        self.n_ids = 0
        self.broadcasts = 0
        self.inhibited = 0
        self.next_timer = 1.0
        self.arousal_t: list[float] = []
        self.arousal_v: list[float] = []
        self.boredom_t: list[float] = []
        self.boredom_v: list[float] = []

        def tally():
            return AffectWelfareTally(negative_valence_bar=_DEFAULT_NEGATIVE_VALENCE_BAR, max_gap_s=_AFFECT_SAMPLE_GAP_CAP_S)

        self._new_tally = tally
        self.tally = tally()
        self.stage_tallies: dict[int, object] = {0: tally()}
        self.stage = 0

    def set_stage(self, stage: int) -> None:
        self.stage = stage
        t = self._new_tally()
        if self.resting:
            t.sleep_started(self._clock.t)
        self.stage_tallies[stage] = t

    async def advance(self, window_s: float) -> float:
        """Start or end a rest; return the awake seconds this window adds."""
        t = self._clock.t
        if self.resting:
            if t < self.rest_until:
                return 0.0
            self.resting = False
            self._audition._in_sleep = False
            await self._affect.affective_reset()
            self.tally.sleep_completed(t)
            self.stage_tallies[self.stage].sleep_completed(t)
            self.rests[-1] = (self.rests[-1][0], t)
            return window_s
        self.awake_since_rest += window_s
        if self.awake_since_rest >= self.t_act:
            self.awake_since_rest = 0.0
            self.resting = True
            self.rest_until = t + self.rest_s
            self._audition._in_sleep = True
            self.tally.sleep_started(t)
            self.stage_tallies[self.stage].sleep_started(t)
            self.rests.append((t, t + self.rest_s))
        return window_s

    def _ids(self, stream: str, events) -> list:  # noqa: ANN001
        out = []
        for ev in events:
            self.n_ids += 1
            out.append((f"{stream}:{self.n_ids}-0", ev))
        return out

    def _collect_affect(self) -> None:
        new = self._fbus.events[self._fbus_seen:]
        self._fbus_seen = len(self._fbus.events)
        pairs = self._ids("affect.out", new)
        self.pending.extend(pairs)
        self.new_this_tick.extend(pairs)
        states = [(i, e) for i, e in pairs if e.type == "affect.state"]
        if states:
            self.provider.observe(states)
        for _, ev in states:
            valence = (ev.payload.get("state") or {}).get("valence")
            if isinstance(valence, (int, float)):
                for tally in (self.tally, self.stage_tallies[self.stage]):
                    tally.observe_state(
                        self._clock.t, float(valence), ev.payload.get("drive_above"), ev.payload.get("drive_ends"),
                        ev.payload.get("drive_reset_ends"), ev.payload.get("drive_open"),
                    )
            drives = ev.payload.get("drives") or {}
            boredom = (drives.get("boredom") or {}).get("value") if isinstance(drives.get("boredom"), dict) else drives.get("boredom")
            if isinstance(boredom, (int, float)):
                self.boredom_t.append(self._clock.t)
                self.boredom_v.append(float(boredom))

    async def after_window(self, audition_events, window_s: float) -> None:  # noqa: ANN001
        pairs = self._ids("audition.out", audition_events)
        self.pending.extend(pairs)
        self.new_this_tick.extend(pairs)
        while self._clock.t >= self.next_timer:  # the affect module's own once-a-second update
            await self._affect._tick(own_update=True)
            await self._affect._maybe_publish_state()
            self.arousal_t.append(self.next_timer)
            self.arousal_v.append(float(self._affect._state.arousal))
            self.next_timer += 1.0
        self._collect_affect()
        self.tick_acc += window_s
        while self.tick_acc >= self.PROCESSING_DT_S - 1e-9:
            self.tick_acc -= self.PROCESSING_DT_S
            self.tick_index += 1
            effective = self.resting_hz
            if self.access is not None:
                _, effective = self.access.step(
                    events=self.new_this_tick, arousal=float(self._affect._state.arousal),
                    dt_s=self.PROCESSING_DT_S, resting_hz=self.resting_hz, ceiling_hz=self.ceiling_hz,
                )
            self.new_this_tick = []
            self.exp_acc += effective / self.ceiling_hz
            if self.exp_acc < 1.0:
                continue
            self.exp_acc = min(1.0, self.exp_acc - 1.0)
            snapshot = await self.workspace.select(
                list(self.pending), {"tick_index": self.tick_index, "is_experiential": True}
            )
            self.pending = []
            self.broadcasts += 1
            self.inhibited += int(snapshot.inhibited)
            await self._audition.on_workspace(snapshot)
            await self._affect.on_workspace(snapshot)
            self._collect_affect()


class _Bus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> str:
        self.events.append(event)
        return f"{len(self.events)}-0"


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t


def region_powers(x: np.ndarray, sr: int) -> np.ndarray:
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    return np.array([spec[(f >= a) & (f < b)].sum() for a, b in zip(REGION_EDGES[:-1], REGION_EDGES[1:])])


async def run(args) -> None:
    repo = Path(args.repo).resolve()
    sys.path.insert(0, str(repo))
    import torch

    torch.set_num_threads(1)
    from kaine.boot.perception_feed import (
        _hearing_band_params,
        _maternal_voice_params,
        _stimulus_source_params,
    )
    from kaine.bus.schema import validate_event
    from kaine.modules.affect.module import Affect
    from kaine.modules.audition.acoustic import SpectralAcousticEncoder
    from kaine.modules.audition.feed import (
        StimulusSourceAudioSchedule,
        StimulusSourceProceduralAudioStream,
        stimulus_source_soundscape_rms,
    )
    from kaine.modules.audition.hearing_band import HEARING_FINAL_STAGE, HEARING_TOP_TONE_HZ
    from kaine.modules.audition.hearing_stage_state import HearingStageState
    from kaine.modules.audition.live import LiveMicConfig, encode_wav
    from kaine.modules.audition.maternal_voice import MaternalVoiceLayer, MaternalVoiceRepertoire
    from kaine.modules.audition.module import Audition

    cfg = tomllib.loads((repo / "config/kaine.toml").read_text())
    feed = dict(cfg["perception_feed"])
    feed["stimulus_source"] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in feed["stimulus_source"].items()}
    acfg, aud = cfg["affect"], cfg["audition"]
    params = _stimulus_source_params({**feed, "stimulus_source": dict(feed["stimulus_source"])})
    voice_params = _maternal_voice_params(feed)
    hearing = _hearing_band_params(feed)
    assert hearing.enabled and voice_params.enabled

    mic = LiveMicConfig()
    sr = int(feed["audio"]["sample_rate"])
    fpb = sr * mic.vad_frame_ms // 1000
    win_blocks = max(1, mic.window_ms // mic.vad_frame_ms)
    schedule = StimulusSourceAudioSchedule(seed=args.seed, sample_rate=sr, channels=1, frames_per_block=fpb)
    bg_rms = stimulus_source_soundscape_rms(schedule, params)
    repertoire = MaternalVoiceRepertoire.load(sample_rate=sr, lowpass_hz=HEARING_TOP_TONE_HZ)
    voice = MaternalVoiceLayer(repertoire, voice_params, seed=args.seed, stimulus_params=params, background_rms=bg_rms)
    added = None
    stimulus_version = ""
    if args.arm == "shipped":
        from kaine.boot.perception_feed import _added_sounds_params
        from kaine.boot.stimulus_version import developmental_stimulus_version
        from kaine.modules.audition.added_sounds import AddedSoundsLayer, AddedSoundsRepertoire

        added_params = _added_sounds_params(feed)
        assert added_params.enabled
        added = AddedSoundsLayer(
            AddedSoundsRepertoire.load(sample_rate=sr, lowpass_hz=HEARING_TOP_TONE_HZ), added_params,
            seed=args.seed, voice_params=voice_params, voice=voice, background_rms=bg_rms,
        )
        stimulus_version = developmental_stimulus_version(cfg)
        layer = voice
    elif args.arm == "none":
        layer = voice
    else:
        layer = AddedSoundsVoice(voice, seed=args.seed, sr=sr, background_rms=bg_rms, arm=args.arm)

    stage_box = [0]
    clock = _Clock()
    awake_box = [0.0]  # awake seconds; equal to the stimulus time without --live
    stream = StimulusSourceProceduralAudioStream(
        schedule, params=params, clock=None, callback=lambda _b: None,  # type: ignore[arg-type]
        voice=layer, awake=lambda: awake_box[0], hearing=hearing, hearing_stage=lambda: stage_box[0], added=added,
    )

    class _RecEncoder(SpectralAcousticEncoder):
        last: list[float] | None = None

        def embed(self, audio_bytes, sample_rate):  # noqa: ANN001
            e = super().embed(audio_bytes, sample_rate)
            self.last = e
            return e

    encoder = _RecEncoder()
    abus = _Bus()
    audition = Audition(
        abus, emotion_model_id="", general_audition=True, transcription_enabled=False, acoustic_encoder=encoder,
        forward_model_units=int(aud.get("forward_model_units", 32)),
        prediction_error_window=int(aud.get("prediction_error_window", 32)),
        auditory_buffer_size=int(aud.get("auditory_buffer_size", 16)),
        baseline_salience=float(aud.get("baseline_salience", 0.4)), alert_salience=float(aud.get("alert_salience", 0.8)),
        entity_clock=clock,  # type: ignore[arg-type]
    )
    torch.manual_seed(args.seed)  # the forward model's initial weights follow the run seed
    audition._acoustic_forward_model = type(audition._acoustic_forward_model)(
        feature_dim=encoder.embedding_dim, units=audition._acoustic_forward_model.units,
        auditory_buffer_size=audition._acoustic_forward_model.auditory_buffer_size,
        context_dim=audition._acoustic_forward_model.context_dim, seed=args.seed,
    )
    baseline_arousal = float(acfg.get("baseline_arousal", 0.3))
    fbus = _Bus()
    if args.live:
        from kaine.boot.factories.affect import make_affect

        affect = make_affect(fbus, dict(acfg), entity_clock=clock)  # type: ignore[arg-type]
        affect.set_development_probe(lambda: True)  # regulation is off in the developmental phase
        audition.set_arousal_provider(lambda: float(affect._state.arousal))
    else:
        audition.set_arousal_provider(lambda: baseline_arousal)
        affect = Affect(
            fbus, clock=clock.now,
            fast_time_constant_s=float(acfg["fast_time_constant_s"]), slow_time_constant_s=float(acfg["slow_time_constant_s"]),
            learning_progress_floor=float(acfg["learning_progress_floor"]),
            learning_progress_span_s=float(acfg["learning_progress_span_s"]),
            learning_progress_bin_s=float(acfg["learning_progress_bin_s"]),
        )
    live = _Live(cfg, affect, audition, clock, fbus) if args.live else None
    lp0 = float(acfg["learning_progress_floor"])
    rule = HearingStageState(hearing, path=None, lp_floor=lp0, learning_progress_span_s=float(acfg["learning_progress_span_s"]))

    def stage_event(stage: int):
        return validate_event(source="development", type="development.hearing_stage", payload={"stage": int(stage)},
                              salience=0.1, timestamp=datetime.now(timezone.utc))

    await affect._handle_peer_event(affect._development_stream, stage_event(0))

    if args.schedule.startswith("fixed:"):
        hold = float(args.schedule.split(":", 1)[1])
        planned = [hold * (i + 1) for i in range(HEARING_FINAL_STAGE)]
        total = hold * (HEARING_FINAL_STAGE + 1)
    else:
        planned = None
        total = float(args.max_hours) * 3600.0

    block_s = fpb / sr
    errs_t, errs_e, alerts = [], [], []
    lp_t, lp_v, lp_stage = [], [], []
    rule_steps: list[tuple[int, float]] = []
    steps: list[float] = []
    # Stimulus minutes: with rests the stimulus runs on while awake time stands still.
    stretch = 1.0 + (live.rest_s / live.t_act if live is not None else 0.0)
    nmin = int(math.ceil(total * stretch / 60.0)) + 2 + (int(math.ceil(live.rest_s / 60.0)) if live is not None else 0)
    reg = np.zeros((nmin, len(REGION_EDGES) - 1))
    reg_n = np.zeros(nmin)
    emb = np.zeros((nmin, encoder.embedding_dim))
    emb_sq = np.zeros(nmin)
    emb_n = np.zeros(nmin)
    k = 0
    next_lp = 1.0
    window_s = win_blocks * block_s
    lp_awake: list[float] = []
    wall0 = time.monotonic()
    while awake_box[0] < total:
        blocks = []
        for _ in range(win_blocks):
            blocks.append(stream.pcm_at(k, maturation_progress=None, awake_seconds=awake_box[0], hearing_stage=stage_box[0]))
            k += 1
        clock.t = k * block_s
        if live is not None:
            awake_box[0] += await live.advance(window_s)
        else:
            awake_box[0] = clock.t
        pcm = b"".join(blocks)
        abus.events.clear()
        await audition._perceive_acoustic(encode_wav(pcm, sample_rate=sr, channels=1), sr, "stimulus_source")
        if live is not None:
            await live.after_window(list(abus.events), window_s)
        for ev in abus.events:
            await affect._handle_peer_event("audition.out", ev)
            pe = ev.payload.get("prediction_error")
            if pe is not None:
                errs_t.append(clock.t)
                errs_e.append(pe)
            if ev.payload.get("alert"):
                alerts.append(clock.t)
        mi = int(clock.t // 60.0)
        if (k // win_blocks) % 4 == 0:
            x = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
            reg[mi] += region_powers(x, sr)
            reg_n[mi] += 1
        if encoder.last is not None:
            e = np.asarray(encoder.last)
            emb[mi] += e
            emb_sq[mi] += float(e @ e)
            emb_n[mi] += 1
        while clock.t >= next_lp:
            # Stimulus seconds tick the reading; the stage owner sees awake seconds (equal without --live).
            awake_now = awake_box[0] if live is not None else next_lp
            lp = affect.audition_learning_progress(stage_box[0])
            lp_t.append(next_lp)
            lp_awake.append(awake_now)
            lp_v.append(np.nan if lp is None else lp)
            lp_stage.append(stage_box[0])
            if planned is None:
                new = rule.observe(awake_now, lp)
                if new is not None:
                    rule_steps.append((new, next_lp))
            next_lp += 1.0
            step_now = False
            if planned is not None:
                step_now = len(steps) < len(planned) and awake_now >= planned[len(steps)]
            else:
                step_now = rule.stage != stage_box[0]
            if step_now and stage_box[0] < HEARING_FINAL_STAGE:
                stage_box[0] += 1
                steps.append(next_lp - 1.0)
                await affect._handle_peer_event(affect._development_stream, stage_event(stage_box[0]))
                if live is not None:
                    live.set_stage(stage_box[0])
        if planned is None and stage_box[0] >= HEARING_FINAL_STAGE and clock.t >= (steps[-1] if steps else 0) + float(args.tail_s):
            break
        if args.progress and (k // win_blocks) % 20000 == 0:
            print(f"t={clock.t / 3600:.2f}h stage={stage_box[0]} wall={time.monotonic() - wall0:.0f}s", flush=True)

    used = int(clock.t // 60.0) + 1
    if added is not None:
        n_slots = int(clock.t // voice_params.slot_seconds) + 1
        kinds = {s: added.slot_sound(s) for s in range(n_slots)}
        melody_slots = [s for s, k in kinds.items() if k is not None and k.kind == "melody"]
        outside_slots = [s for s, k in kinds.items() if k is not None and k.kind == "outside_voice"]
    else:
        melody_slots = [s for s, kind in getattr(layer, "slot_kinds", {}).items() if kind == "melody"]
        outside_slots = [s for s, kind in getattr(layer, "slot_kinds", {}).items() if kind == "outside_proxy"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    live_fields: dict = {"live": bool(live is not None)}
    if live is not None:
        import json as _json

        lt_arr, la_arr = np.asarray(lp_t), np.asarray(lp_awake)
        live_fields.update(
            lp_awake=la_arr,
            steps_awake=np.asarray([float(la_arr[np.searchsorted(lt_arr, s)]) for s in steps]),
            rests=np.asarray(live.rests, dtype=np.float64).reshape(-1, 2),
            t_act=live.t_act, rest_s=live.rest_s,
            broadcasts=live.broadcasts, inhibited=live.inhibited,
            arousal_t=np.asarray(live.arousal_t), arousal_v=np.asarray(live.arousal_v),
            boredom_t=np.asarray(live.boredom_t), boredom_v=np.asarray(live.boredom_v),
            welfare=_json.dumps({
                "overall": live.tally.snapshot(),
                "by_stage": {str(k): t.snapshot() for k, t in live.stage_tallies.items()},
            }),
            awake_s=awake_box[0],
        )
    np.savez_compressed(
        out,
        **live_fields,
        seed=args.seed, arm=args.arm, schedule=args.schedule, lp0=lp0,
        bin_s=float(acfg["learning_progress_bin_s"]), span_s=float(acfg["learning_progress_span_s"]),
        w_sat=hearing.saturation_window_seconds, d_min=0.0, d_max=hearing.max_dwell_seconds,  # no minimum dwell since full-span saturation
        earliest_release_s=rule.earliest_release_seconds,
        err_t=np.asarray(errs_t), err_e=np.asarray(errs_e, dtype=np.float64), alert_t=np.asarray(alerts),
        lp_t=np.asarray(lp_t), lp_v=np.asarray(lp_v), lp_stage=np.asarray(lp_stage, dtype=np.int8),
        steps=np.asarray(steps), rule_steps=np.asarray(rule_steps, dtype=np.float64).reshape(-1, 2),
        reg=reg[:used], reg_n=reg_n[:used], emb=emb[:used], emb_sq=emb_sq[:used], emb_n=emb_n[:used],
        region_edges=np.asarray(REGION_EDGES), window_s=win_blocks * block_s,
        melody_slots=np.asarray(melody_slots), outside_slots=np.asarray(outside_slots),
        stimulus_version=stimulus_version,
        voice_slots=np.asarray([s for s in range(int(clock.t // voice_params.slot_seconds)) if voice.plan_for(s, clock.t)]),
        wall_s=time.monotonic() - wall0, sim_s=clock.t,
    )
    print(f"done {out} sim={clock.t / 3600:.2f}h wall={time.monotonic() - wall0:.0f}s steps={steps}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--arm", choices=("shipped", "none", "melody", "melody_proxy"), default="shipped")
    ap.add_argument("--schedule", default="fixed:14400")
    ap.add_argument("--max-hours", type=float, default=30.0)
    ap.add_argument("--tail-s", type=float, default=7200.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--live", action="store_true", help="arousal from the affect module, state-cycle rests and broadcast context")
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
