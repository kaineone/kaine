/*
 * SPDX-FileCopyrightText: 2026 KAINE
 * SPDX-License-Identifier: MIT
 */

package com.kaine.registry;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry that maps entity identifiers to {@link FreezeRecovery} data.
 *
 * <p>The registry is keyed by arbitrary entity identifiers (e.g., {@code Integer},
 * {@code Long}, {@code UUID}, or any custom {@code EntityId} implementation).
 * It provides static methods for registering, retrieving, and deregistering
 * freeze‑recovery data.</p>
 */
public final class FreezeRecoveryRegistry {

    private static final Map<Object, FreezeRecovery> REGISTRY = new ConcurrentHashMap<>();

    // Private constructor to prevent instantiation.
    private FreezeRecoveryRegistry() {
    }

    /**
     * Registers a {@link FreezeRecovery} entry for the given entity identifier.
     *
     * @param entityId the identifier of the entity; must not be {@code null}
     * @param data     the freeze‑recovery data to associate with the entity
     * @throws NullPointerException if {@code entityId} is {@code null}
     */
    public static void register(Object entityId, FreezeRecovery data) {
        if (entityId == null) {
            throw new NullPointerException("entityId must not be null");
        }
        REGISTRY.put(entityId, data);
    }

    /**
     * Retrieves the {@link FreezeRecovery} data associated with the given entity identifier.
     *
     * @param entityId the identifier of the entity
     * @return the associated {@link FreezeRecovery} data, or {@code null} if none is registered
     */
    public static FreezeRecovery get(Object entityId) {
        return REGISTRY.get(entityId);
    }

    /**
     * Unregisters the freeze‑recovery entry for the given entity identifier.
     *
     * @param entityId the identifier of the entity
     */
    public static void unregister(Object entityId) {
        REGISTRY.remove(entityId);
    }

    /**
     * Checks whether a freeze‑recovery entry exists for the given entity identifier.
     *
     * @param entityId the identifier of the entity
     * @return {@code true} if an entry exists, {@code false} otherwise
     */
    public static boolean contains(Object entityId) {
        return REGISTRY.containsKey(entityId);
    }
}