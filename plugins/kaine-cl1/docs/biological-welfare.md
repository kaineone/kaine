# Biological-welfare posture

KAINE is, unusually, built around *entity welfare*: its license is the
Cognitive Architecture License, and its safety lives in the action boundary and
in gated, welfare-load-bearing maintenance. Running its forward models on **living
neural tissue** raises a second, distinct welfare question, and this document is
where the project answers it.

## The goal is real tissue; the simulator is how we prepare for it

The point of this subproject is to run KAINE's predictive processors on **real CL1
cultures**. Time on the machines, or purchasing them, is prohibitively
expensive; real CL1 hardware is not available to this project yet, so the
**free simulator** (`cl.is_simulator() == True`) is what we build and validate
on: seeded Poisson data and replayed recordings, no living cells.

That is not a smaller ambition; it is the responsible order of operations. We wire
the whole system, characterise every stimulation pattern, and prove the codecs and
the closed loop against the simulator **first**, so that if and when real
tissue access becomes available, we arrive ready, with safe, tested stim
patterns and a working pipeline, not a blank slate on someone else's expensive and
living hardware.

## What applies when real tissue is in the loop

Bringing a real culture online adds a review layer *on top of* KAINE's existing
entity-welfare gates:

1. **Institutional oversight.** Use of biological neural cultures follows Cortical
   Labs' terms and any applicable ethical / institutional review for the cells
   involved. This repo does not procure, culture, or manage tissue and takes no
   position that circumvents that oversight.
2. **Stimulation limits are safety limits.** The SDK's charge/current ceilings
   (±3 µA, ≤3 nC/phase, ≤200 Hz burst) are not just API constraints; on hardware
   they bound charge injection into living cells. Our codecs stay well inside them
   and are validated in the simulator before any hardware run.
3. **Two questions, kept separate.** "Is the *KAINE entity* being treated well?"
   (CAL, upstream) and "Is the *neural culture* being treated well?" (this layer)
   are different questions with different review bodies. We do not let one stand
   in for the other.
4. **Characterise in simulation before hardware.** No stim pattern reaches a real
   culture that has not first been characterised in the simulator. Hardware runs
   are an explicit, reviewed step, never an accidental default, so the transition
   from sim to tissue is deliberate.

## Two welfare stacks

A project that puts a *synthetic mind's* forward models into *biological neurons*
sits on two welfare stacks at once: the entity's (CAL, upstream) and the
culture's (this layer). They stay separate, with separate review. During the
current simulator phase the second stack is not yet engaged; the preparation we do
now is precisely what lets us engage it responsibly when access arrives.
