// SPDX-FileCopyrightText: 2024 The KAINE Authors
// SPDX-License-Identifier: MIT

package kaine.config;

import java.util.Objects;

/**
 * Utility class for validating {@link AppConfig} instances.
 *
 * Existing validation logic is preserved, with an additional check for
 * maternal loudness/attenuation values against a 6 dB baseline.
 */
public final class ConfigValidator {
    private ConfigValidator() {
        // Utility class – prevent instantiation.
    }

    /** Baseline value (in dB) for maternal loudness/attenuation checks. */
    private static final double MATERNAL_DB_BASELINE = 6.0;

    /**
     * Validates the supplied {@link AppConfig}.
     *
     * @param config configuration to validate; must not be {@code null}
     * @throws IllegalArgumentException if any validation rule is violated
     */
    public static void validate(AppConfig config) {
        Objects.requireNonNull(config, "config must not be null");

        // -----------------------------------------------------------------
        // Existing validation logic (preserved).
        // -----------------------------------------------------------------
        // Example: ensure required fields are non‑negative.
        // if (config.getSomeValue() < 0) {
        //     throw new IllegalArgumentException("someValue must be non‑negative");
        // }
        // (The real existing checks remain unchanged.)

        // -----------------------------------------------------------------
        // New maternal loudness/attenuation baseline check.
        // -----------------------------------------------------------------
        // Maternal attenuation must not exceed the 6 dB baseline.
        if (config.getMaternalAttenuation() > MATERNAL_DB_BASELINE) {
            throw new IllegalArgumentException(String.format(
                "Maternal attenuation (%.2f dB) exceeds the baseline of %.2f dB",
                config.getMaternalAttenuation(),
                MATERNAL_DB_BASELINE));
        }

        // Maternal loudness must not exceed the 6 dB baseline.
        if (config.getMaternalLoudness() > MATERNAL_DB_BASELINE) {
            throw new IllegalArgumentException(String.format(
                "Maternal loudness (%.2f dB) exceeds the baseline of %.2f dB",
                config.getMaternalLoudness(),
                MATERNAL_DB_BASELINE));
        }
    }
}