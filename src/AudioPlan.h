// SPDX-FileCopyrightText: 2022-2026 KAINE Project
// SPDX-License-Identifier: MIT

#ifndef KAINE_AUDIOPLAN_H
#define KAINE_AUDIOPLAN_H

#include <vector>
#include "Sound.h"

class AudioPlan {
public:
    AudioPlan(bool planned);
    void AddRequired(const Sound& sound);
    void AddOptional(const Sound& sound);
    std::vector<Sound> GetAllSounds() const;
private:
    bool planned_;
    std::vector<Sound> requiredSounds_;
    std::vector<Sound> optionalSounds_;
};

#endif // KAINE_AUDIOPLAN_H