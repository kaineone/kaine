/*
 * SPDX-FileCopyrightText: 2026 KAINE
 * SPDX-License-Identifier: MIT
 */

package com.kaine.registry;

/**
 * Represents the freeze/recovery state of an entity.
 */
public final class FreezeRecovery {

    private final boolean frozen;
    private final long recoveryTimestamp;

    /**
     * Constructs a new FreezeRecovery instance.
     *
     * @param frozen            whether the entity is currently frozen
     * @param recoveryTimestamp the epoch millisecond at which the entity should recover
     */
    public FreezeRecovery(boolean frozen, long recoveryTimestamp) {
        this.frozen = frozen;
        this.recoveryTimestamp = recoveryTimestamp;
    }

    /**
     * Returns {@code true} if the entity is frozen, {@code false} otherwise.
     *
     * @return frozen state
     */
    public boolean isFrozen() {
        return frozen;
    }

    /**
     * Returns the configured recovery timestamp.
     *
     * @return recovery timestamp in epoch milliseconds
     */
    public long getRecoveryTimestamp() {
        return recoveryTimestamp;
    }
}