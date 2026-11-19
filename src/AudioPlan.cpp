// SPDX-FileCopyrightText: 2022-2026 KAINE Project
// SPDX-License-Identifier: MIT

#include "AudioPlan.h"

AudioPlan::AudioPlan(bool planned) : planned_(planned) {}

void AudioPlan::AddRequired(const Sound& sound) {
    requiredSounds_.push_back(sound);
}

void AudioPlan::AddOptional(const Sound& sound) {
    optionalSounds_.push_back(sound);
}

std::vector<Sound> AudioPlan::GetAllSounds() const {
    std::vector<Sound> all = requiredSounds_;
    if (planned_) {
        // Optional sounds are added only when the plan is marked as planned.
        all.insert(all.end(), optionalSounds_.begin(), optionalSounds_.end());
    }
    return all;
}