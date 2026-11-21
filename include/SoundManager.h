// SPDX-FileCopyrightText: 2024 The KAINE Authors
// SPDX-License-Identifier: MIT

#ifndef KAINE_SOUND_MANAGER_H
#define KAINE_SOUND_MANAGER_H

#include <string>
#include <unordered_map>
#include <unordered_set>
#include <filesystem>

class SoundManager {
public:
    explicit SoundManager(const std::string& manifestPath);
    void loadAddedSounds(const std::filesystem::path& directory);
    bool hasSound(const std::string& name) const;
private:
    // Set of sound names defined in the manifest.
    std::unordered_set<std::string> manifestSounds_;
    // Map of sound name to its file path.
    std::unordered_map<std::string, std::string> soundMap_;
    // Other members may exist; unchanged.
};

#endif // KAINE_SOUND_MANAGER_H