# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The minimal, continuous, learnable embodiment control surface (the producer).

This is the ``intent.avatar.*`` producer the body-agnostic control plane
(:mod:`kaine.modules.mundus.module`) left unbuilt: nothing in the build emitted
any per-tick motor command, so the entity could not drive a body on its own.
This closes that *producer gap* — deliberately as **continuous control** rather
than a symbolic verb menu.

The entity's body here is a small, continuous, feedback-coupled action space it
learns to operate: four continuous locomotion/gaze rates plus one interaction
trigger (``drive``, ``yaw_rate``, ``gaze_yaw``, ``gaze_pitch``, ``interact``),
gaze decoupled from the body, ``strafe`` deferred. Each control tick the surface
emits a clamped :class:`ControlCommand`, forwarded by Mundus to the body; the
loop is closed by feeding an **efference copy** of the emitted command plus the
proprioceptive feedback into KAINE's *existing* forward-model machinery
(Soma's :class:`~kaine.modules.soma.forward.SubstrateForwardModel`) — no new
learner is introduced.

Emergent, not hard-wired
------------------------
Only two things are **provided** here (a training/safety scaffold, cited below —
honestly, *not* an innate mechanism):

1. the **structure** of the action space — few degrees of freedom, gaze
   decoupled from the body, one interaction primitive with a provided
   target-resolver; and
2. the **freeze-then-free progression** (:data:`MOTOR_STAGES`) that starts a
   newborn at the fewest DOF and frees the rest as competence is demonstrated.

No code here scripts a gait or maps an intent to a pre-solved world effect. The
control **policy** (:class:`MotorPolicy`), the action→perception **coupling**,
the **gaze-aiming** that resolves interaction targets, and the **competence**
that frees each DOF all emerge from the entity's own exploration; the default
policy is *quiescent* (emits nothing) precisely so no gait is baked in — a real
learner is injected at the seam.

Scaffold citations (developmental motor learning):
  * Bernstein (1967) — skilled action masters a redundant body; beginners freeze
    then free degrees of freedom. (We *impose* the unlock order as a pragmatic
    safety scaffold, not because an external unlock order is innate.)
  * O'Regan & Noe (2001) — perception is mastery of the lawful way sensory input
    changes with one's own action; gaze is kept decoupled so that law is
    learnable.
  * Wolpert, Ghahramani & Jordan (1995) — closed-loop control via forward models
    / efference copy; the emitted command's efference copy is fed to the forward
    model to predict -> compare -> correct.
"""
from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from kaine.modules.mundus.channels import CONTINUOUS_CHANNEL_RANGE

log = logging.getLogger(__name__)

# Canonical continuous motor channels the entity operates directly, in order.
# `strafe` is deliberately DEFERRED (design §4): it is not a channel yet, so a
# policy that emits it is ignored, and it is absent from every command.
MOTOR_CHANNELS: tuple[str, ...] = (
    "drive",
    "yaw_rate",
    "gaze_yaw",
    "gaze_pitch",
    "interact",
)

# The freeze-then-free motor curriculum (design §7). PROVIDED training/safety
# scaffold (Bernstein 1967) — NOT an innate mechanism. A newborn starts with the
# fewest DOF that permit locomotion; the rest are freed one stage at a time only
# as competence on the currently-free axes is demonstrated (measured, never
# scheduled). `strafe` (a putative M4) is deferred and so is not represented.
MOTOR_STAGES: tuple[tuple[str, ...], ...] = (
    ("drive", "yaw_rate"),                                          # M1: crawl/turn
    ("drive", "yaw_rate", "gaze_yaw", "gaze_pitch"),                # M2: + decoupled gaze
    ("drive", "yaw_rate", "gaze_yaw", "gaze_pitch", "interact"),    # M3: + interact
)


def clamp_channel(name: str, value: float) -> float:
    """Clamp one channel value to its declared range at the boundary."""
    lo, hi = CONTINUOUS_CHANNEL_RANGE.get(name, (-1.0, 1.0))
    return max(lo, min(hi, float(value)))


@dataclass(frozen=True)
class ControlCommand:
    """One tick of continuous motor command — the entity's emitted action.

    Only the canonical channels exist as fields; ``strafe`` is deferred and has
    no field, so it can never be part of a command.
    """

    drive: float = 0.0
    yaw_rate: float = 0.0
    gaze_yaw: float = 0.0
    gaze_pitch: float = 0.0
    interact: float = 0.0

    def channels(self) -> dict[str, float]:
        """The command as a channel->value mapping (all canonical channels)."""
        return {
            "drive": self.drive,
            "yaw_rate": self.yaw_rate,
            "gaze_yaw": self.gaze_yaw,
            "gaze_pitch": self.gaze_pitch,
            "interact": self.interact,
        }

    @classmethod
    def from_channels(cls, channels: Mapping[str, float]) -> "ControlCommand":
        """Build a command from a channel mapping (unknown channels ignored)."""
        return cls(
            drive=float(channels.get("drive", 0.0)),
            yaw_rate=float(channels.get("yaw_rate", 0.0)),
            gaze_yaw=float(channels.get("gaze_yaw", 0.0)),
            gaze_pitch=float(channels.get("gaze_pitch", 0.0)),
            interact=float(channels.get("interact", 0.0)),
        )

    def is_zero(self) -> bool:
        return not any(v != 0.0 for v in self.channels().values())


@dataclass(frozen=True)
class MotorFeedback:
    """Proprioceptive feedback the body returns for one control tick.

    The sensory *consequence* of the emitted command — resulting avatar velocity,
    heading, gaze direction, a contact/collision signal, and interact
    success/failure — time-aligned with the outgoing action so the forward model
    can compare its prediction to what actually happened.
    """

    forward_velocity: float = 0.0
    heading: float = 0.0
    gaze_yaw: float = 0.0
    gaze_pitch: float = 0.0
    contact: bool = False
    interact_success: bool = False

    def to_vector(self) -> list[float]:
        return [
            float(self.forward_velocity),
            float(self.heading),
            float(self.gaze_yaw),
            float(self.gaze_pitch),
            1.0 if self.contact else 0.0,
            1.0 if self.interact_success else 0.0,
        ]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MotorFeedback":
        """Build feedback from a ``mundus.proprio`` bus payload (best-effort)."""
        return cls(
            forward_velocity=float(payload.get("forward_velocity", 0.0) or 0.0),
            heading=float(payload.get("heading", 0.0) or 0.0),
            gaze_yaw=float(payload.get("gaze_yaw", 0.0) or 0.0),
            gaze_pitch=float(payload.get("gaze_pitch", 0.0) or 0.0),
            contact=bool(payload.get("contact", False)),
            interact_success=bool(payload.get("interact_success", False)),
        )


@runtime_checkable
class MotorPolicy(Protocol):
    """Maps an observation to raw (unclamped, unmasked) action scalars.

    Implementations are the entity's LEARNED control policy — they are the
    emergent part. The surface masks (curriculum) and clamps whatever a policy
    returns, so a policy may return any subset of channels and any magnitude.
    """

    def __call__(self, observation: Any) -> Mapping[str, float]:
        """Return the policy's desired setpoints for the given observation."""


class QuiescentMotorPolicy:
    """The honest default policy: emit nothing.

    A newborn has *no learned policy yet*, so the built-in default drives no
    channel — it scripts no gait. A real learned policy (e.g. an active-inference
    seam over the entity's own exploration) is injected in its place; nothing
    here bakes in a motor mapping.
    """

    def __call__(self, observation: Any) -> Mapping[str, float]:
        return {}


class MotorCurriculum:
    """Freeze-then-free DOF progression, gated by demonstrated competence.

    PROVIDED training/safety scaffold (Bernstein 1967) — *not* innate. The stage
    order is imposed for learnability and so a newborn is not handed its full
    continuous+interaction surface at once. Advancement is **measured, never
    scheduled**: a degree of freedom is freed only when the motor-competence
    readout on the currently-free axes crosses threshold — a *falling*
    forward-model error over a window of real observed ticks. No wall-clock term
    enters the decision; elapsed time alone never frees a DOF.
    """

    def __init__(
        self,
        *,
        stages: tuple[tuple[str, ...], ...] = MOTOR_STAGES,
        competence_threshold: float = 0.05,
        min_samples: int = 32,
        window: int = 64,
    ) -> None:
        if not stages:
            raise ValueError("stages must be non-empty")
        if competence_threshold <= 0.0:
            raise ValueError("competence_threshold must be positive")
        if min_samples <= 0:
            raise ValueError("min_samples must be positive")
        if window < min_samples:
            raise ValueError("window must be >= min_samples")
        self._stages = stages
        self._threshold = float(competence_threshold)
        self._min_samples = int(min_samples)
        self._errors: deque[float] = deque(maxlen=int(window))
        self._stage_index = 0

    @property
    def stage(self) -> int:
        """0-based index of the current curriculum stage (M1 == 0)."""
        return self._stage_index

    def free_channels(self) -> frozenset[str]:
        """Channels currently freed for control; all others are frozen to zero."""
        return frozenset(self._stages[self._stage_index])

    def at_final_stage(self) -> bool:
        return self._stage_index >= len(self._stages) - 1

    def record(self, error: float) -> None:
        """Feed one forward-model prediction error (the competence signal)."""
        if math.isfinite(error):
            self._errors.append(float(error))

    def competence(self) -> Optional[float]:
        """Rolling mean prediction error, or None until ``min_samples`` seen.

        Lower is better (the forward model predicts the coupled consequences of
        the free axes well); ``None`` means not enough evidence yet to judge.
        """
        if len(self._errors) < self._min_samples:
            return None
        return sum(self._errors) / len(self._errors)

    def ready_to_advance(self) -> bool:
        """True when demonstrated competence permits freeing the next DOF.

        Purely competence-gated: enough samples AND a low enough rolling error.
        Never a function of elapsed time.
        """
        if self.at_final_stage():
            return False
        comp = self.competence()
        return comp is not None and comp <= self._threshold

    def maybe_advance(self) -> bool:
        """Free the next DOF if competence permits; returns True if advanced."""
        if not self.ready_to_advance():
            return False
        self._stage_index += 1
        # Fresh evidence must be gathered on the newly-enlarged action space
        # before the *next* DOF can be freed — competence is per-stage.
        self._errors.clear()
        log.info(
            "mundus/control: motor curriculum advanced to stage %d (free=%s)",
            self._stage_index,
            sorted(self.free_channels()),
        )
        return True


class EfferenceLoop:
    """Closes the sensorimotor loop through the EXISTING forward model.

    On each tick the emitted command's **efference copy** is concatenated with
    the proprioceptive feedback and fed to a forward model that predicts the next
    such vector, compares it to what arrives, and corrects online (predict ->
    compare -> correct; Wolpert et al. 1995). This REUSES Soma's
    :class:`~kaine.modules.soma.forward.SubstrateForwardModel` (a frozen CfC
    reservoir + online linear readout) — it introduces **no new learner**. The
    forward model is injectable so the closed loop can be exercised without torch
    in tests; the default is the real substrate forward model.
    """

    # 5 command channels (efference copy) + 6 proprioception scalars.
    FEATURE_DIM = len(MOTOR_CHANNELS) + 6

    def __init__(self, forward_model: Any = None) -> None:
        self._fm = forward_model

    @property
    def forward_model(self) -> Any:
        """The forward model, constructing the default lazily on first use."""
        if self._fm is None:
            # Reuse Soma's existing forward model — do NOT add a new learner.
            from kaine.modules.soma.forward import SubstrateForwardModel

            self._fm = SubstrateForwardModel(feature_dim=self.FEATURE_DIM)
        return self._fm

    def _feature(self, command: ControlCommand, feedback: MotorFeedback) -> list[float]:
        vec = [command.channels()[name] for name in MOTOR_CHANNELS]
        vec.extend(feedback.to_vector())
        return vec

    def observe(self, command: ControlCommand, feedback: MotorFeedback) -> float:
        """Feed one (efference copy, feedback) pair; return the prediction error."""
        feature = self._feature(command, feedback)
        return float(self.forward_model.step(feature))


class ContinuousMotorSurface:
    """The continuous motor producer — emits per-tick control, closes the loop.

    Composes the (emergent) :class:`MotorPolicy`, the provided-scaffold
    :class:`MotorCurriculum`, and the :class:`EfferenceLoop` over the existing
    forward model. :meth:`emit` produces a clamped, curriculum-masked
    :class:`ControlCommand` each tick (zeroed while inhibited);
    :meth:`observe_feedback` feeds the coupled feedback back through the forward
    model and lets demonstrated competence free the next DOF.
    """

    def __init__(
        self,
        *,
        policy: Optional[MotorPolicy] = None,
        curriculum: Optional[MotorCurriculum] = None,
        efference: Optional[EfferenceLoop] = None,
    ) -> None:
        self._policy: MotorPolicy = policy or QuiescentMotorPolicy()
        self._curriculum = curriculum or MotorCurriculum()
        self._efference = efference or EfferenceLoop()
        # The embodied stage / birth gate. The surface is INERT before the
        # birth-transition event (design §2, §8): the developmental-stage
        # capability flips this on when the stage becomes `embodied` and the
        # embodied world takes over as the sense source. Until then the surface
        # emits the null command regardless of policy — the reciprocal half of
        # the birth-handoff contract. (This is on top of Mundus's two-layer gate
        # and locus gate, which the forwarding path enforces separately.)
        self._active = False

    @property
    def active(self) -> bool:
        """True once the birth handoff has activated the embodied surface."""
        return self._active

    def on_birth(self) -> None:
        """Activate the surface on the birth-transition event (stage → embodied).

        The reciprocal half of the developmental-stage birth handoff: the
        embodied world becomes the sense source and this control surface becomes
        active. Idempotent.
        """
        if not self._active:
            log.info("mundus/control: birth handoff — embodiment surface active")
        self._active = True

    def deactivate(self) -> None:
        """Return the surface to its inert (pre-birth) state."""
        self._active = False

    @property
    def policy(self) -> MotorPolicy:
        return self._policy

    @property
    def curriculum(self) -> MotorCurriculum:
        return self._curriculum

    @property
    def efference(self) -> EfferenceLoop:
        return self._efference

    def emit(self, observation: Any = None, *, inhibited: bool = False) -> ControlCommand:
        """Produce this tick's command: policy -> curriculum mask -> clamp.

        A workspace inhibition zeroes the action (returns the null command), so
        nothing is forwarded while the entity is inhibited — the reciprocal of
        Volition returning no intents. The surface is likewise inert (null
        command) before the birth handoff (:meth:`on_birth`). Channels frozen by
        the curriculum are forced to zero; freed channels are clamped to range at
        the boundary (the policy is never trusted).
        """
        if inhibited or not self._active:
            return ControlCommand()
        raw = dict(self._policy(observation) or {})
        free = self._curriculum.free_channels()
        masked = {
            name: (clamp_channel(name, raw.get(name, 0.0)) if name in free else 0.0)
            for name in MOTOR_CHANNELS
        }
        return ControlCommand.from_channels(masked)

    def intent_payload(self, command: ControlCommand) -> dict[str, Any]:
        """The ``intent.avatar.control`` payload for an emitted command."""
        return {"channels": command.channels()}

    def observe_feedback(self, command: ControlCommand, feedback: MotorFeedback) -> float:
        """Close the loop: efference copy + feedback -> forward model -> competence.

        Returns the forward-model prediction error and lets the curriculum free
        the next DOF if that error has fallen enough to demonstrate competence.
        """
        error = self._efference.observe(command, feedback)
        self._curriculum.record(error)
        self._curriculum.maybe_advance()
        return error
