// SPDX-FileCopyrightText: 2024 The KAINE Authors
// SPDX-License-Identifier: MIT

#include "SoundManager.h"
#include <filesystem>
#include <string>

// Constructor and other methods are unchanged.
// ...

void SoundManager::loadAddedSounds(const std::filesystem::path& directory) {
    // Load sounds from the given directory.
    // Only treat sounds that are explicitly listed in the manifest as present.
    // Unlisted added sounds are ignored (no implicit addition).
    for (const auto& entry : std::filesystem::directory_iterator(directory)) {
        if (!entry.is_regular_file()) {
            continue;
        }
        if (entry.path().extension() != ".wav") {
            continue;
        }
        std::string name = entry.path().stem().string();
        // Only add if this sound name appears in the manifest's listed sounds.
        if (manifestSounds_.find(name) == manifestSounds_.end()) {
            // Unlisted sound – treat as absent.
            continue;
        }
        // Insert or update the sound entry.
        soundMap_[name] = entry.path().string();
    }
}

// Other member functions remain unchanged.
// ...
